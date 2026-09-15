> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Rückmeldungen an den Template-Autor

Dieser Ordner ist **Ausgang und Protokoll zugleich**:

| Was | Datei | Wann |
| :--- | :--- | :--- |
| Ein gesammelter Eintrag | `JJJJ-MM-TT-<thema>.md` + `.json` | sobald der Assistent etwas gefunden hat (`--add`) |
| Dein eigenes Feedback | `feedback.md` | wann immer du magst — Fragen beantworten, Freitext |
| Bereits gesendete Einträge | `sent/…` | beim Versand dorthin verschoben |
| Protokoll einer Sendung | `JJJJ-MM-TT_HHMM.json` | je Sendung eine Datei mit Zeitpunkt, Ziel und vollständiger Nutzlast |

Die `.md` neben jedem Eintrag ist zum Lesen da: Schon **vor** dem Versand steht im Repo, was hinausgehen
soll — sichtbar im Diff, nicht in einer versteckten Datei. Die `.json` daneben ist dasselbe in der Form, die
der Empfänger verarbeitet.

Der Ordner ist standardmäßig **versioniert**. Das ist sein ganzer Zweck: Der Assistent sendet autonom und
fragt nicht vorher, aber nichts verlässt das Projekt unbemerkt — jede Sendung taucht im nächsten Diff auf und
lässt sich auch Monate später nachlesen.

**Ausnahme auf Wunsch:** Ist das Repo öffentlich, wäre die Rückmeldung darin für jeden lesbar. Dann nimmt
`.gitignore` die Nutzlast-Dateien aus (`docs/ai/template-feedback/*.json`, gesetzt über
`feedback.py --enable --protokoll lokal`); diese README bleibt versioniert, damit nachlesbar bleibt, **dass**
gesendet wird. `--status` zeigt, welcher der beiden Fälle gilt.

**Steht hier nichts, wurde nie etwas gesendet.** Die Rückmeldung ist standardmäßig aus und wird genau einmal
angeboten (Checkliste „Einrichtung abschließen").

| Womit | Befehl |
| :--- | :--- |
| Ein Satz, sofort und immer möglich | `/feedback <Text>` bzw. `python .claude/scripts/feedback.py --direkt "<Text>"` |
| Zustand ansehen | `python .claude/scripts/feedback.py --status` |
| Sehen, was gesendet würde | `python .claude/scripts/feedback.py --plan` |
| Abschalten | `python .claude/scripts/feedback.py --disable` |
| Protokoll lokal halten / wieder versionieren | `python .claude/scripts/feedback.py --enable --protokoll lokal\|versionieren` |

Was gesendet wird und was nicht, steht in `AGENTS.md` § „Freiwillige Rückmeldung an den Template-Autor".
Kurzfassung: nie Dateien, nie Projektbezug, nie Namen oder Zahlen aus dem Projekt — nur das Muster, das auch
jemandem hilft, der dieses Projekt nie sehen wird.
