> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Tests — {{PROJEKTNAME}}

## Pyramide

- **Unit:** kleinste testbare Einheiten (Funktionen, einzelne Module), isoliert von Datenbank/Netzwerk. Größter
  Anteil, schnellster Lauf.
- **Integration:** Zusammenspiel mehrerer Module/Schichten (z. B. Datenzugriff + Geschäftslogik), ggf. gegen
  eine echte Test-Datenbank.
- **End-to-End (E2E):** kompletter Ablauf durch die Anwendung (z. B. im Browser), so nah wie möglich am
  echten Nutzungsverhalten. Kleinster Anteil, langsamster Lauf, bei UI-relevanten Änderungen ausführen.

## Pflichtläufe

| Prüfung | Befehl | Wann |
| :--- | :--- | :--- |
| Lint | `{{LINT_BEFEHL}}` | vor jedem Commit, in der CI |
| Typecheck | `{{TYPECHECK_BEFEHL}}` | vor jedem Commit, in der CI |
| Unit-/Integrationstests | `{{TEST_BEFEHL}}` | vor jedem Commit, in der CI |
| E2E-Tests | `{{E2E_BEFEHL}}` | bei UI-relevanten Änderungen |

*(Platzhalter-Befehle beim Anlegen des Projekts (Checkliste „Neues Projekt") durch echte Skripte/Befehle ersetzen.)*

## Testdaten

- Testdaten mit festem, erkennbarem Präfix anlegen (z. B. `e2e-`/`test-`), damit sie von echten Daten
  unterscheidbar sind.
- Nach jedem Testlauf aufräumen (Cleanup), damit Testläufe wiederholbar bleiben und keine Testdaten in
  produktionsnahen Umgebungen liegen bleiben.

## CI

`.github/workflows/ci.yml` führt Lint, Typecheck und Unit-/Integrationstests bei jedem Push aus. E2E-Tests
laufen lokal bei UI-Änderungen (Aufnahme in die CI ist ein Ausbauschritt, siehe „Ungetestet").

## Manuelle Verifikation

*(offen — z. B. ein konkreter Klickpfad oder API-Aufruf, mit dem ein Feature manuell nachvollzogen wird, wenn
automatisierte Tests (noch) nicht ausreichen)*

## Ungetestet

Bereiche ohne (ausreichende) Testabdeckung ehrlich benennen statt zu verschweigen — Ausbau bei Bedarf über
`docs/ai/backlog.md`.

*(offen — Vorlage, noch keine Bereiche identifiziert)*
