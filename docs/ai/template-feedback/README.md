> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Protokoll der Rückmeldungen an den Template-Autor

Hier liegt **jede** Rückmeldung, die dieses Projekt an den Autor des Templates gesendet hat — je Sendung eine
Datei `JJJJ-MM-TT_HHMM.json` mit Zeitpunkt, Zieladresse und der vollständigen Nutzlast.

Der Ordner ist **versioniert**. Das ist sein ganzer Zweck: Der Assistent sendet autonom und fragt nicht
vorher, aber nichts verlässt das Projekt unbemerkt — jede Sendung taucht im nächsten Diff auf und lässt sich
auch Monate später nachlesen.

**Steht hier nichts, wurde nie etwas gesendet.** Die Rückmeldung ist standardmäßig aus und wird genau einmal
angeboten (Checkliste „Einrichtung abschließen").

| Womit | Befehl |
| :--- | :--- |
| Zustand ansehen | `python .claude/scripts/feedback.py --status` |
| Sehen, was gesendet würde | `python .claude/scripts/feedback.py --plan` |
| Abschalten | `python .claude/scripts/feedback.py --disable` |

Was gesendet wird und was nicht, steht in `AGENTS.md` § „Freiwillige Rückmeldung an den Template-Autor".
Kurzfassung: nie Dateien, nie Projektbezug, nie Namen oder Zahlen aus dem Projekt — nur das Muster, das auch
jemandem hilft, der dieses Projekt nie sehen wird.
