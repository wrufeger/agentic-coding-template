> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Lokale Einrichtung — {{PROJEKTNAME}}

## Voraussetzungen

*(offen — z. B. Laufzeitumgebung + Version, Datenbank, weitere Dienste)*

## Einrichtung

```
cp .env.example .env      # Werte anpassen
cp .mcp.json.example .mcp.json   # falls MCP-Server genutzt werden, Werte anpassen
{{INSTALL_BEFEHL}}
{{DEV_START_BEFEHL}}
```

*(Platzhalter-Befehle beim Zuschneiden des Templates durch echte Befehle ersetzen.)*

## Umgebungsvariablen

Nur Namen und Zweck hier dokumentieren, niemals Werte. Echte Werte stehen ausschließlich in `.env`
(gitignored).

| Variable | Zweck |
| :--- | :--- |
| *(offen)* | *(offen — Vorlage, siehe `.env.example` für aktuelle Namen)* |

## Nützliche Befehle

| Befehl | Zweck |
| :--- | :--- |
| `{{LINT_BEFEHL}}` | Lint |
| `{{TYPECHECK_BEFEHL}}` | Typecheck |
| `{{TEST_BEFEHL}}` | Unit-/Integrationstests |
| `{{E2E_BEFEHL}}` | End-to-End-Tests |
