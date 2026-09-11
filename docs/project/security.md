> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Sicherheit — {{PROJEKTNAME}}

## Secrets-Regeln

- Secrets (Passwörter, API-Schlüssel, Token, Zertifikate) niemals im Klartext committen.
- Ablageorte: `.env` (lokal) und die jeweilige Secret-Verwaltung der Zielumgebung — beide gitignored bzw.
  außerhalb des Repos.
- `.env.example`/`.mcp.json.example` enthalten nur Platzhaltermuster, nie echte Werte.
- Wird ein Secret versehentlich committet: sofort rotieren (nicht nur aus dem Verlauf entfernen), dann erst
  bereinigen.

## Freigaben

Aktionen, die ausdrückliche Freigabe von {{AUFTRAGGEBER}} brauchen (Beispiele, beim Zuschneiden des Templates
projektspezifisch ergänzen):

- Produktions-Deployments.
- Löschen von Daten, Konten oder kritischen Konfigurationen.
- Anlegen/Ändern von Zugangsdaten und Berechtigungen.

Siehe `AGENTS.md` § Tabu-Bereich für die generelle Regel; projektspezifische Ergänzungen hier eintragen.

## Risiko-Liste

| Nr. | Risiko | Schweregrad (Auswirkung × Wahrscheinlichkeit) | Status | Maßnahme |
| :--- | :--- | :--- | :--- | :--- |
| 1 | *(offen — Vorlage, noch kein Risiko erfasst)* | – | offen | *(offen)* |
