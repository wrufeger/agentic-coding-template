> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Checklisten für die Zusammenarbeit

Werkzeugneutrale Arbeitsanweisungen (gelten für jeden Assistenten, siehe `AGENTS.md`). {{AUFTRAGGEBER}} kann sie
wörtlich als Anweisung geben, z. B. „Führe die Checkliste Aufgabe abschließen aus
(`docs/ai/checklists.md` § Aufgabe abschließen)". Welche zusätzliche Mechanik ein bestimmtes Werkzeug dafür anbietet (automatisierter
Aufruf, Ablauf in einer separaten Session o. Ä.), steht in der jeweiligen werkzeugspezifischen Ergänzungsdatei
(siehe `AGENTS.md` § „Werkzeugspezifische Ergänzungsdateien"), nicht in dieser Checkliste.

## Idee oder Änderungswunsch aufnehmen

Läuft, sobald {{AUFTRAGGEBER}} ein neues Feature, eine Idee oder einen Änderungswunsch äußert — auch
nebenbei im Gespräch. **Nicht sofort bauen.** Zwischen „das wäre gut" und der ersten Zeile Code liegen eine
Analyse und eine Entscheidung; sonst entsteht etwas, das niemand so bestellt hat.

1. **Wortlaut festhalten.** Der Wunsch in {{AUFTRAGGEBER}}s eigenen Worten, unverändert — er ist die
   Messlatte für alles Weitere. Nachfragen nur, wenn ohne die Antwort nicht einmal klar ist, worum es geht.
2. **Analysieren, nicht schätzen.** Ein Konzept in `docs/project/konzepte/<thema>.md` (Format siehe README
   dort): Ausgangslage mit Fundstellen `Datei:Zeile`, dann **Optionen** — je Option Beschreibung, Vorteile,
   Nachteile, Aufwand. Dazu gehört immer auch die Option „nichts tun" mit ihren Folgen. Was schon entschieden
   ist (`docs/project/decisions.md`), wird geprüft: Widerspricht der Wunsch einer bestehenden Entscheidung,
   steht das **oben** im Konzept, nicht als Fußnote.
3. **Empfehlung aussprechen** — eine Option, begründet in wenigen Sätzen. Eine Empfehlung ohne Alternativen
   ist keine; es müssen mindestens zwei echte Wege dastehen, zwischen denen man wählen kann.
4. **Zur Entscheidung vorlegen** als Frage in `docs/ai/questions.md` (`Q<n>`), Optionen `a)`/`b)`/`c)`, die
   Empfehlung gekennzeichnet. Bis zur Antwort wird nichts gebaut.
5. **Nach der Entscheidung:** ADR in `docs/project/decisions.md` — was entschieden wurde, was verworfen, mit
   welcher Folge. Dann abschätzen:
   - **Umfang** in der Einheit des Projekts (Personentage, S/M/L) — für die empfohlene Option, nicht für alle.
   - **Was dafür gebraucht wird:** Bibliotheken, ein MCP-Server aus `.claude/mcp-katalog.md`, ein Regelsatz
     aus `docs/project/coding_rules.d/`, ein Skill, der noch fehlt. Fehlendes Werkzeug ist ein eigener
     Arbeitsschritt, kein Nebenbei.
   - **Grobe Aufteilung:** Stories in `docs/project/stories/` für Abschnitte mit eigener Begründung, sonst
     Aufgaben. Noch nicht startklar machen — das ist die Checkliste „Block vorbereiten".
6. **Priorität und Zeitpunkt festlegen.** {{AUFTRAGGEBER}} nennt beides; {{ORCHESTRATOR}} setzt **seine
   eigene** Einschätzung daneben, statt zuzustimmen. In den Backlog kommt der Mittelwert (siehe
   `docs/ai/README.md` § Backlog). **Weichen beide um mehr als eine Stufe ab, steht der Grund dafür in einer
   Zeile am Punkt** — genau dort steckt meistens eine Information, die der andere nicht hatte.
7. **Verbuchen:** Backlog-Punkt(e) mit Thema, Prioritäten, Zeitpunkt, Aufwand und Verweis auf Konzept und
   ADR. Aufgaben in `docs/ai/tasks.md` entstehen **nur für das, was jetzt gemacht wird** — der Rest bleibt
   im Backlog, bis sein Zeitpunkt kommt.

**Abkürzung erlaubt, aber benannt:** Ist der Wunsch klein und eindeutig (ein Tippfehler, ein Feldname, eine
Zeile Konfiguration), entfallen Konzept und ADR — er wird direkt Aufgabe oder Backlog-Punkt. Die Abkürzung
wird ausgesprochen („mache ich direkt als Aufgabe, kein Konzept"), damit {{AUFTRAGGEBER}} widersprechen kann.
Im Zweifel für die Analyse: Ein überflüssiges Konzept kostet eine halbe Stunde, ein übersehener Widerspruch
zu einer Entscheidung kostet den Umbau.

## Block vorbereiten

Läuft **vor** einem größeren Vorhaben — einem Feature, einem Umbau, einer Welle von Aufgaben. Zweck: Der
Block soll danach **ohne Rückfragen durchlaufen**. {{AUFTRAGGEBER}} beantwortet alles **einmal**, in einem
Zug, und ist danach nicht mehr gebunden.

Die Vorbereitung kostet Zeit und spart mehr, als sie kostet: Eine Frage, die vorher geklärt ist, kostet
Sekunden. Dieselbe Frage mitten in der Umsetzung kostet den Faden — und wenn niemand da ist, der sie
beantwortet, kostet sie den ganzen Lauf.

1. **Umfang abstecken.** Was gehört zum Block, was ausdrücklich nicht. Das „nicht" wird aufgeschrieben, sonst
   wächst der Block während der Arbeit.
2. **Bestand recherchieren, bevor geplant wird.** Was existiert schon, welche Dateien werden angefasst,
   welche Entscheidungen sind bereits getroffen (`docs/project/decisions.md`) und welche davon widersprechen
   dem Vorhaben. Unabhängige Recherchen parallel. **Ohne diesen Schritt entstehen Fragen, die der Code
   längst beantwortet** — und genau die nerven {{AUFTRAGGEBER}} zu Recht.
3. **In Aufgaben oder Stories schneiden**, je mit Ziel in einem Satz und einer prüfbaren Abnahmebedingung
   („Fertig wenn"). Eine Aufgabe = ein Ergebnis. Was mehr als etwa fünf Schritte braucht, wird geteilt.
4. **Startklar-Prüfung je Aufgabe.** Startklar ist eine Aufgabe erst, wenn **alle fünf** zutreffen:

   | Kriterium | Woran man es erkennt |
   | :--- | :--- |
   | Ziel eindeutig | Ein Satz, der sagt, was danach anders ist — ohne „und ggf." |
   | Abnahme prüfbar | Man kann hinterher zeigen, dass es erfüllt ist (Testlauf, Aufruf, Datei) |
   | Entscheidungen getroffen | Keine offene Frage, von der das Vorgehen abhängt |
   | Vorbedingungen erfüllt | Zugänge, Daten, vorangehende Aufgaben vorhanden |
   | Unbekanntes recherchiert | Keine Stelle, an der erst beim Anfassen klar wird, wie es geht |

   Fehlt eines, ist die Aufgabe **nicht startklar** — sie bekommt eine `Offen:`-Zeile und wird nicht begonnen.
5. **Alle offenen Punkte in einem Block fragen.** Nicht nacheinander, nicht verteilt über die Sitzung: eine
   nummerierte Liste, je Frage vorgegebene Antwortmöglichkeiten und, wo es eine gibt, eine gekennzeichnete
   Empfehlung. Sortiert danach, **wie viel sie blockieren** — was den ganzen Block aufhält, steht oben.
   Fragen, die sich durch eine Recherche beantworten lassen, werden **nicht gestellt**, sondern recherchiert.
6. **Antworten verbuchen:** Entscheidungen als ADR in `docs/project/decisions.md`, die `Offen:`-Zeilen der
   betroffenen Aufgaben leeren, Stories von `Entwurf` auf `abgestimmt` setzen.
7. **Reihenfolge festlegen und vorlegen:** welche Aufgabe wann, was parallel laufen kann, wo ein Zwischenstand
   sinnvoll ist. Damit weiß {{AUFTRAGGEBER}}, was in seiner Abwesenheit passiert.

**Unbeaufsichtigter Lauf.** Sagt {{AUFTRAGGEBER}}, dass er weg ist, gilt zusätzlich:

- Es wird **die vorbereitete Reihenfolge abgearbeitet**, keine neue Arbeit erfunden und kein Umfang erweitert.
- Taucht doch etwas Unvorhergesehenes auf, wird es notiert (`questions.md`/`tasks.md`) und **mit der nächsten
  Aufgabe weitergemacht** — nicht gewartet.
- Ist alles Verbleibende blockiert, wird **angehalten** und der Fragenblock hinterlegt. Nicht auf Verdacht
  weiterbauen, nur um beschäftigt zu wirken.
- **Unumkehrbares bleibt liegen** (Tabu-Bereich, Produktionszugriff, Löschen, Rechteänderungen) — auch dann,
  wenn es den Block aufhält. Abwesenheit ist keine Freigabe.
- Beim Zurückkommen steht **eine** Bilanz bereit: was fertig ist mit Belegen, was liegt und warum, und der
  gebündelte Fragenblock.

## Aufgabe beginnen

Läuft **vor jeder Aufgabe** im Hauptkontext, dauert im Normalfall Sekunden.

1. `AI-CONFIG.md` lesen — beide Abschnitte, nicht nur „Betrieb". Die Datei ist Steuerung, kein Protokoll.
2. Abgleich gegen den zuletzt umgesetzten Stand: `python .claude/scripts/sync-config.py --check`. Meldet er
   nichts, weiter mit Schritt 4.
3. Offene Punkte umsetzen: `--apply` erledigt die Ergänzungen. Was löscht oder projektweit ersetzt, wird
   vorgelegt und erst nach der Zusage von {{AUFTRAGGEBER}} ausgeführt (`--apply --yes`). **Keine
   Standardantwort annehmen** — ohne Zusage bleibt es offen, und die Aufgabe läuft mit dem alten Stand.
4. `docs/ai/board.md` lesen: Stand, nächster Schritt, offene Freigaben.
5. **Jetzt fragen, was unklar ist** — und nur jetzt. Steht ein größerer Block oder ein Feature an, werden die
   offenen Punkte **vor** dem ersten Handgriff geklärt: Hier kostet eine Frage Sekunden, mitten in der
   Umsetzung kostet sie den Faden. Was danach auftaucht, wird notiert statt erfragt (`AGENTS.md`
   § Grundregeln, „Rückfragen gehören an den Anfang").

Wer das überspringt, arbeitet unter Umständen mit Einstellungen, die längst geändert wurden — etwa mit
einem Werkzeug, dessen Dateien noch fehlen, oder unter einem Rufnamen, den es nicht mehr gibt.

## Aufgabe abschließen

Läuft **nach jeder abgeschlossenen Aufgabe** im Hauptkontext (Orchestrator), nie bei einem Worker — nicht
erst am Sitzungsende.

Journal, Aufgabenstand und neue Fragen sind zu diesem Zeitpunkt bereits nachgezogen: Das passiert laufend
während der Arbeit, solange die Belege frisch sind (`AGENTS.md` § Grundregeln). Diese Checkliste räumt auf,
was sich angesammelt hat, und sichert das Ergebnis.

1. **Beleg prüfen:** Testlauf, Commit-Hash oder ein Aufruf von außen. Pflichtläufe aus
   `docs/project/testing.md` grün. Ohne Beleg keine Abnahme — dann nur `Stand <Datum>:` in
   `docs/ai/tasks.md` aktualisieren und die Aufgabe offen lassen. Dabei prüfen, ob die Änderung einen
   Tabellenwert in `AI-CONFIG.md` berührt (Stack, Befehle, Regelsätze, Werkzeuge — `AGENTS.md`
   § Grundregeln) und die Datei bei Bedarf nachziehen.
2. **Archivieren:** als ✅ markierte Aufgaben mit Volltext nach `docs/ai/tasks_archive.md`, verbuchte Fragen
   nach `docs/ai/questions_archive.md` — **alles, was seit dem letzten Lauf fertig geworden ist, in einem
   Zug**. Daraus folgt ein einheitliches Verschiebedatum je Lauf; uneinheitliche Daten im Archiv zeigen an,
   dass nicht laufweise archiviert wurde, sondern nachträglich aus der Erinnerung.
   Nummern (`T<n>`/`Q<n>`) bleiben gültig und werden nie neu vergeben.
   Aufgaben unter „nur für {{AUFTRAGGEBER}}" nur auf dessen Meldung hin abhaken; Antworten in deren
   `* Antwort:`-Zeilen genauso verbuchen — delegierte Aufgaben wandern in den oberen Abschnitt, erweiterte
   Rechte mit Datum ins Journal.
3. **Journal ergänzen und verdichten:** fehlt ein Eintrag zur gerade abgeschlossenen Aufgabe, jetzt
   nachtragen. Ältere Einträge nach den Regeln im Kopf von `docs/ai/ledger.md` zusammenfassen — Commit-Hashes,
   Nummern, Versionen und Pfade bleiben immer erhalten.
4. **Doku-Index:** neue Dateien in `docs/README.md` eintragen, Datenstände der geänderten Dateien prüfen.
5. **Board:** `docs/ai/board.md` **überschreiben**, nicht ergänzen — es ist eine Momentaufnahme auf einer
   Bildschirmseite (Form: `docs/ai/README.md` § Board). Dabei ausdrücklich **entfernen**: erledigte Punkte
   unter „Als Nächstes" (auch durchgestrichene und solche mit „erledigt am …"), beantwortete Fragen unter
   „Ausstehende Freigaben", und alles in der Kurzbilanz, das die nächste Entscheidung nicht mehr beeinflusst.
   Das Board schrumpft bei diesem Schritt öfter, als es wächst.
6. **Commit per Pathspec:** `git add <pathspec …>`, nie ein catch-all; kurze Message im Repo-Stil. Committet
   wird die abgenommene Arbeit, nicht ein Zeitabschnitt. Secrets, Archive und Originalmedien bleiben draußen
   (`.gitignore` prüfen). Fremde uncommittete Änderungen anderer Sitzungen nicht stillschweigend mitnehmen —
   sichten, dann entscheiden.
7. **Bilanz an {{AUFTRAGGEBER}}:** Ergebnis zuerst, Belege (Hash, Zahlen), offene Punkte und Fragen mit
   Nummern — **gebündelt**. Was während der Umsetzung aufgetaucht ist, wurde unterwegs in `questions.md`
   bzw. `tasks.md` abgelegt statt sofort erfragt; hier kommt es zusammengefasst auf den Tisch, zusammen mit
   jeder Annahme, unter der weitergearbeitet wurde.
8. **Logging** (falls eingeschaltet, `AGENTS.md` § Logging): Commit als
   `[orchestrator] [commit] <hash> <message>` schreiben — das Log ist Mitschnitt, kein Ersatz für Journal
   oder Beleg.
9. **Kontext freigeben:** Der Detailkontext der erledigten Aufgabe wird nicht mehr gebraucht, der Stand liegt
   vollständig in Git und `docs/ai/`. Werkzeuge mit Kontext-Komprimierung (Claude Code: `/compact`) hier
   einsetzen; steht die nächste Aufgabe schon fest, sie dabei erwähnen.

## Delegation

Bewährte Arbeitsweise: das teure/starke Modell (Orchestrator) plant, integriert und prüft; die breite Arbeit
machen parallele Worker (günstigeres/schnelleres Modell). So bleibt der Kontext des Orchestrators klein und die
Arbeit bezahlbar (siehe `AGENTS.md` § Modell-/Kostenlogik).

- **Wann delegieren:** Codebase-Analysen über mehrere Verzeichnisse, Web-/Doku-Recherche, unabhängige
  Baustellen (mehrere Endpunkte/Komponenten/Dateien), Routine-Doku-Pflege.
- **Nicht delegieren:** kleine Einzeldatei-Fixes, alles, was `docs/ai/` beschreibt (nur der Orchestrator
  schreibt dort), finale Commits, finale Urteile/Freigaben.
- **Auftrags-Regeln:** jeder Auftrag nennt Kontext (2–3 Sätze), konkreten Liefergegenstand, Format des
  Ergebnisses, was zu ignorieren ist (Build-Ordner, `node_modules`, `.git`, generierte Dateien) und die
  **erwartete Dauer** — der Orchestrator schätzt sie vor dem Start und misst den Lauf später dagegen
  (siehe „Laufende Worker überwachen").
- Unabhängige Worker **immer gleichzeitig** starten, nicht nacheinander.
- Worker-Ergebnisse sind Rohmaterial: der Orchestrator verifiziert Kernaussagen stichprobenartig am Code, bevor
  sie in Board, Doku oder Entscheidungen wandern.
- Ein Worker, der sich festgefressen hat, wird nicht endlos weitergefüttert — Auftrag schärfen und neu starten
  ist günstiger.

### Laufende Worker überwachen

**Wer delegiert, wartet nicht blind.** Ein Worker, der läuft, kostet Zeit und Geld, auch wenn er beschäftigt
aussieht. Dass er seine Aufgabenzeile aktualisiert, ist **kein** Beleg für Fortschritt.

**Die Schätzung macht der Orchestrator, vor dem Start.** Wer den Auftrag schneidet, weiß am besten, wie groß
er ist — der Worker sieht sich selbst nicht von außen und neigt dazu, das Ende für nah zu halten. Also: vor
dem Start eine erwartete Dauer festlegen, sie dem Worker im Auftrag nennen (er hat dann eine Referenz) und
den Lauf gegen diese Zahl messen, nicht gegen eine feste Uhrzeit.

Anhaltspunkte für die Schätzung — und wann daraufhin zum ersten Mal nachgesehen wird:

| Auftragsart | erwartete Dauer | erste Prüfung nach | abbrechen ab |
| :--- | :--- | :--- | :--- |
| Kurzcheck: lesen, zählen, Existenz prüfen | unter 1 Minute | 2 Minuten | 5 Minuten |
| Recherche über mehrere Dateien, Fundstellen belegen | 2 bis 5 Minuten | 8 Minuten | 15 Minuten |
| Umsetzung in wenigen Dateien, mit Beleg | 3 bis 8 Minuten | 12 Minuten | 20 Minuten |
| Umsetzung mit eigenen Testläufen über mehrere Dateien | 8 bis 15 Minuten | 20 Minuten | 25 Minuten |
| Breite Web-Recherche mit Prüfung jeder Quelle | 5 bis 15 Minuten | 20 Minuten | 25 Minuten |

Die Faustregel dahinter, falls ein Auftrag in keine dieser Zeilen passt: **erste Prüfung beim Doppelten der
geschätzten Dauer, mindestens aber nach zwei Minuten.** Je länger der Auftrag geplant war, desto knapper wird
dieser Abstand — bei einem Lauf über zehn Minuten steht schon zu viel auf dem Spiel, um ihn erst nach zwanzig
anzuschauen.

Was auf die erste Prüfung folgt:

| Stand | Was der Orchestrator tut |
| :--- | :--- |
| erste Prüfung | Zwischenstand anfordern: was steht, was fehlt, was kam dazwischen |
| danach keine Besserung | Entscheiden: fertigmachen lassen, eskalieren oder abbrechen — nicht weiterlaufen lassen |
| Abbruchmarke erreicht | Abbrechen. Die Schätzung war um eine Größenordnung daneben, also der Zuschnitt auch |

Zusätzlich gilt ein harter Deckel unabhängig von jeder Schätzung: **ab etwa 25 Minuten oder 250.000 Token wird
abgebrochen**, auch wenn der Lauf als lang geplant war.

**Die Bewertung bleibt beim Orchestrator.** Der Worker liefert Fakten — was fertig ist, was aussteht, was
unerwartet kam. Ob das noch im Rahmen liegt, entscheidet der, der den Auftrag geschnitten hat. Eine
Selbsteinschätzung des Workers ist ein Hinweis, kein Urteil: Wer seit zwanzig Minuten läuft und „fast fertig"
meldet, hat sich schon einmal verschätzt.

Erwartbar längere Läufe gibt es (breite Recherche, viele Testläufe). Dann wird das **vorher** im Auftrag
gesagt und beim Start vermerkt — unerwartet lang ist etwas anderes als lang geplant.

Beim Eingreifen gibt es drei Wege, in dieser Reihenfolge zu prüfen:

1. **Fertigmachen lassen**, wenn der Zwischenstand zeigt, dass nur noch Tests oder Feinschliff fehlen.
2. **Stärkeres Modell ansetzen**, wenn der Worker an der Sache selbst hängt und nicht an ihrem Umfang. Ein
   Auftrag, der ein schwächeres Modell überfordert, wird durch Wiederholung nicht leichter — er gehört an
   die nächsthöhere Stufe, mit vollständigem Kontext des bisherigen Laufs (siehe „Eskalation" unten).
3. **Abbrechen und neu zuschneiden**, wenn der Auftrag schlicht zu groß war.

Halbfertiges gehört dabei nie ins Repo: entweder ein Stand, der für sich trägt, oder gar keine Änderung.

**Häuft sich das, war der Zuschnitt falsch.** Dann wird der Auftrag nicht noch einmal gleich gestellt, sondern
geteilt: auf mehrere Worker, die nebeneinander an getrennten Dateien arbeiten, oder in Teilschritte, die
nacheinander laufen und je für sich prüfbar sind. Ein Auftrag, der während des Laufs mehrfach nachgebessert
wird, ist ebenfalls ein Zeichen dafür — jede Nachbesserung entwertet einen Teil der schon geleisteten Arbeit.
Dann lieber abbrechen und neu schneiden, statt nachzubessern.
- **Eskalation:** Scheitert ein Worker **zweimal** an derselben Aufgabe, wird nicht ein drittes Mal derselbe
  Auftrag gestellt. Entweder (a) lag der Fehler am Auftrag — dann schärfen und einmal neu starten — oder (b)
  an die stärkere Denkstufe/„Experten"-Rolle eskalieren, mit vollständigem Kontext beider Fehlversuche
  (ursprünglicher Auftrag, was jeweils versucht wurde, welche Ausgabe kam zurück, betroffene Dateien, bereits
  ausgeschlossene Ursachen). Den Befund danach verbuchen (Ledger, ggf. Coding-Regeln/Backlog). Eskalation
  ist billiger als die dritte Wiederholung.
- Nach jeder Welle: Lint + Typecheck laufen lassen, betroffene Funktionen real ausprobieren; „fertig" nur mit
  Beleg; Journal laufend nachziehen (`AGENTS.md` § Grundregeln).
- Nach jeder Umsetzungswelle kann eine kurze Optimierungsrunde über die neu geschriebenen Stellen laufen —
  Ziel ist Verständlichkeit und Kürze, Geschwindigkeit nur, wo sie ohne Mehrkomplexität zu haben ist;
  höchstens zwei Runden, Verhalten und Tests müssen unverändert bleiben. Ist der Aufwand größer, wird daraus
  ein Vorschlag im Backlog statt einer Änderung.
- Bei eingeschaltetem Logging (`AGENTS.md` § Logging): vor jeder Welle die Entscheidung als
  `[orchestrator] [decision]` schreiben, jede Delegation als `[delegate]`, Start/Ende der Worker als
  `[start]`/`[end]` — sofern das Werkzeug das nicht automatisch tut (Claude Code: Hooks, `CLAUDE.md` § 7).

## Doku prüfen und nachziehen

Nachziehen und Prüfen sind derselbe Vorgang: wer nachzieht, gleicht zuerst gegen den echten Stand ab.

Bereich `project` — nach jeder Feature-Welle, jedem produktionsrelevanten Bugfix:

- Neue Schnittstelle/neues Konzept/neue Tabelle → `docs/project/architecture.md` bzw. `features.md` ergänzen
  (knapp, im vorhandenen Stil).
- Neue Konvention gelernt (z. B. eine Framework-Falle) → `docs/project/coding_rules.md`, als Regel formuliert,
  nicht als Anekdote.
- Neue/geänderte Tests → `docs/project/testing.md`.
- `AGENTS.md`/`CLAUDE.md` nur anfassen, wenn sich Grundregeln ändern.
- Schwere Fehler (Build-/Startfehler, Produktionsausfälle, Sicherheitsrelevantes) nach
  `docs/project/incidents/README.md` dokumentieren.
- Grundsatz: Doku beschreibt den IST-Zustand, nicht den Wunsch. Was noch nicht gebaut ist, gehört auf die
  Backlog oder ins Fragen-Board. Kein Doku-Eintrag ohne Prüfung am Code.

Bereich `ai` — Arbeitsordner `docs/ai/` auf Ordnung prüfen, ohne Code-Zugriff:

- Als ✅ markierte Aufgaben, die noch nicht in `tasks_archive.md` stehen; Aufgaben ohne `Stand <Datum>:` oder
  mit einem Stand, der älter ist als der letzte Journaleintrag dazu; doppelt vergebene oder übersprungene
  Nummern.
- Beantwortete Fragen ohne Bestätigungszeile darunter; verbuchte Fragen, die noch nicht im Archiv sind.
- Veraltetes Board (Stand, der nicht mehr zum letzten Journaleintrag passt).
- **Tote Querverweise:** zitierte Kürzel, deren Ziel es nicht (mehr) gibt — `T<n>`, `Q<n>`, `ADR-<n>`,
  `S<n>`, `B<n>`. Wo eine Mechanik dafür bereitsteht, wird sie genutzt statt von Hand gesucht (bei
  Claude Code: `python .claude/scripts/check-refs.py`). Verwaiste Ziele — vorhanden, aber nirgends zitiert —
  sind kein Fehler, aber ein Hinweis: entweder fehlt der Verweis, oder der Eintrag ist überflüssig geworden.
- Journaleinträge ohne Beleg (Testlauf, Commit-Hash, Aufruf von außen); Einträge in falscher Reihenfolge
  (neuester gehört nach oben) oder mit Laufnummer statt Uhrzeit in der Überschrift.
- Überholte Punkte im Backlog (bereits umgesetzt oder nicht mehr relevant), und Anmerkungen, die sich am
  Dateiende gesammelt haben, statt eine Frage oder Aufgabe geworden zu sein.
- **Board-Hygiene:** erledigte Punkte unter „Als Nächstes", beantwortete Fragen unter „Ausstehende
  Freigaben", eine Kurzbilanz, die über eine Bildschirmseite hinausgeht.
- **Freie Dateien in `docs/ai/`:** alles außerhalb der festen Dateiliste (`docs/ai/README.md` § Dateien)
  gehört woandershin — Konzepte und Analysen nach `docs/project/konzepte/`, abgegrenzte Vorhaben nach
  `docs/project/stories/`, Entscheidungen nach `docs/project/decisions.md`.
- **Vorlagenreste:** Kopfzeilen, die noch „Status: Vorlage, noch nicht projektspezifisch" tragen, obwohl die
  Datei längst Projektinhalt hat, oder ein Statuswort außerhalb des Vokabulars in `docs/README.md`
  § Konventionen.

## Neues Projekt

Wenn ein komplett neues Projekt aus diesem Template entstehen soll — leer oder mit einer schon feststehenden
Idee, das Formular `AI-CONFIG.md` deckt beides ab:

0. Projekt per `git clone <Template-URL> <projekt>` anlegen, damit Projekt und Template eine gemeinsame
   Git-Historie teilen (Voraussetzung für spätere Updates per Merge, siehe § „Template-Update" unten); danach
   `cd <projekt> && git remote rename origin template && git remote add origin <eigene-Repo-URL>`.
   Diesen Schritt kann auch der Assistent übernehmen — es genügt, ihm im Template-Checkout zu sagen, wo das
   Projekt entstehen soll („Erstelle eine neue Anwendung in `<pfad>`"; „leeres Projekt" überspringt das
   Interview zu Ziel und Stack). Ein Zielordner, der bereits Inhalt hat, gehört zur Checkliste „Projekt
   nachrüsten" — dort wird nie hineingeklont.
   **Alternative:** direkt im Template-Checkout einen Branch anlegen (`git switch -c projekt/<name>`). Dann
   entsteht das Projekt als Branch, der Basis-Commit wird aus dem Standard-Branch abgeleitet und Updates
   laufen später per Merge von dort — ohne zusätzlichen Remote. Auf dem Standard-Branch selbst (`main`/
   `master`) verweigert der Anlege-Schritt die Arbeit, sonst würde das Template seine Platzhalter verlieren.
1. **Erst fragen, dann anlegen.** Hat {{AUFTRAGGEBER}} nicht ausdrücklich „leeres Projekt" gesagt und ist
   `AI-CONFIG.md` noch unausgefüllt, wird **einmal** nachgefragt: „Soll ein leeres Projekt entstehen — nur
   das Gerüst mit Standardwerten? a) nein, vier kurze Fragen jetzt beantworten (Empfehlung) b) ja, leer
   anlegen." Bei „ja" geht es ohne Interview weiter; bei „nein" folgen genau vier Fragen, auf einmal gestellt:
   **Projektname**, **welche KI-Werkzeuge bleiben sollen**, **Stack** (ein Satz — daraus im selben Zug die
   passenden Regelsätze vorschlagen und bestätigen lassen) und **worum es geht** (ein bis zwei Sätze).
   Bei den Werkzeugen ist das **gerade laufende vorausgewählt**, soweit erkennbar: Der Assistent vererbt
   seine Prozessumgebung an Shell-Aufrufe, und einige Werkzeuge setzen dort eine Marke (Claude Code
   `CLAUDECODE=1`, Gemini CLI, Cline, Cursor). Einen herstellerübergreifenden Standard dafür gibt es
   nicht — für die Copilot-CLI, Aider und Windsurf existiert gar keine Marke. Wird nichts erkannt, wird
   gefragt statt geraten; vorausgewählt heißt außerdem nicht entschieden.
   Die Antworten werden **in `AI-CONFIG.md` eingetragen**, nicht nur gemerkt: Die Datei ist die Quelle und
   bleibt dauerhaft im Projekt. Alles Übrige — Auftraggeber, Rufname des Assistenten, Logging, Wartung —
   bleibt auf Standard und ist dort jederzeit änderbar; das wird {{AUFTRAGGEBER}} in einem Satz gesagt.
   Wer die Datei lieber selbst ausfüllt, tut das statt des Interviews; alles darin ist optional, leer lassen
   ist gültig (Kommentare je Zeile erklären, was bei „leer" passiert). Bei Unklarheit kurz rückfragen statt
   zu raten.
2. `python .claude/scripts/create-project.py --dry-run` ausführen, Plan (Werte, zu entfernende Dateien,
   Logging-Schalter, offene Platzhalter) gegen {{AUFTRAGGEBER}} prüfen.
3. `python .claude/scripts/create-project.py --apply` ausführen: ersetzt Platzhalter im ganzen Repo (außer
   `AI-CONFIG.md`, `docs/ai/checklists.md`, `.claude/skills/create-project/SKILL.md`), entfernt nicht genutzte
   Werkzeug-Dateien (nur wenn `KI-Werkzeuge` gesetzt ist), setzt `AI_LOG`/`AI_LOG_LEVEL` in `AGENTS.md` und
   schreibt die Werte (und bei vorhandenem Remote `template` den Basis-Commit) in `.claude/template.json`.
4. Aus den `AI-CONFIG.md`-Abschnitten befüllen: `docs/project/project_description.md` (Ziel, Nutzer, Scope aus
   Features, Non-Scope, Risiken), `docs/project/architecture.md` (Architektur-Text), `docs/project/
   coding_rules.md` § „Stack-spezifisch" (aus Stack), erste Aufgaben aus Features nach `docs/ai/tasks.md`,
   offene Platzhalterwerte/Lücken nach `docs/ai/questions.md`, Stand nach `docs/ai/board.md`. Bei leerem
   `AI-CONFIG.md` bleiben die Skelette bestehen — nur Name/Datum sind gesetzt.
5. Werkzeug-Verweise prüfen: `docs/README.md`-Index und `AGENTS.md`-Tabelle „Werkzeugspezifische
   Ergänzungsdateien" gegen die tatsächlich noch vorhandenen Dateien.
6. Ersten `docs/ai/ledger.md`-Eintrag „Projekt angelegt aus AI-CONFIG.md" schreiben — mit allen Setzungen
   (eingesetzte Werte, entfernte Dateien, Logging-Schalter).
7. `python .claude/scripts/create-project.py --finish` ausführen (prüft die Vorbedingungen aus Schritt 4/6,
   schreibt danach `AI-CONFIG.md` fort statt sie zu löschen: Freitext-Abschnitte durch einen Verweis auf
   `docs/project/` ersetzt, Vermerk in Zeile 1, „Betrieb"/„Einrichtung" bleiben unverändert).
8. `grep -rn "{{" .` prüfen — nur die Scripte in `.claude/scripts/` (Code-Literale bzw. Kopfkommentare,
   siehe `no_replace` in `.claude/template.json`) und `AI-CONFIG.md` dürfen noch Platzhalter zeigen, alles
   andere klären.
9. Commit per Pathspec nach Freigabe (Checkliste „Aufgabe abschließen").
10. **Einrichtung abschließen**, sobald {{AUFTRAGGEBER}} das ausdrücklich sagt — nicht automatisch an dieser
    Stelle: einmal fragen, ob die Einrichtung abgeschlossen ist oder noch etwas kommt (Checkliste
    „Einrichtung abschließen" unten). Bei „abgeschlossen" die dortigen Schritte ausführen; bei „noch nicht"
    bleibt alles liegen, bis {{AUFTRAGGEBER}} es später auslöst.

## Projekt nachrüsten

Wenn ein bestehendes Repo (eigene Historie, kein Template-Klon) die Agentic-Coding-Grundausstattung
nachträglich bekommen soll:

1. Aus dem Template-Checkout heraus: `python <template>/.claude/scripts/apply-template.py --target
   <ziel-repo>` ausführen — kopiert `AGENTS.md`, die Werkzeug-Verweisdateien, `.claude/`, `docs/ai/`,
   `docs/project/`-Skelette, `AI-CONFIG.md` u. a. ins Ziel, ohne dort etwas zu überschreiben (Ausnahmen/Details
   im Kopfkommentar des Scripts). Schreibt `.claude/template.json` mit Basis-Commit/Remote-URL des Templates
   und legt im Ziel den Remote `template` an.
2. Im Ziel-Repo weiterarbeiten: `git status` sichten, den Arbeitsbaum **committen** (Voraussetzung für
   Schritt 3). Dateien, die im Ziel schon existierten, wurden nicht überschrieben — sie werden in Schritt 3
   zusammengeführt.
3. **Struktur-Migration** (Entscheidung von {{AUFTRAGGEBER}}: `AI-CONFIG.md` § `Struktur-Migration` = `ja` |
   `nein` | `fragen`; beim Default `fragen` den Plan zeigen und einmal im Gespräch nachfragen, ohne Antwort
   nicht migrieren). Bei „ja":
   - Vorhandene KI-Arbeitsordner (heißen je nach Projekt `fable/`, `ai/`, `ki/`, `docs/fable/`, …) auf die
     Template-Struktur umstellen: Board, Aufgaben, Fragen, Ledger, Backlog wandern unter ihren
     Template-Namen nach `docs/ai/`. Verschieben statt kopieren, damit die Versionsgeschichte erhalten bleibt.
     Kollidiert eine Altdatei mit einer schon vorhandenen, wird sie danebengelegt statt überschrieben (nur
     inhaltsgleiche Dubletten entfallen). Dateien in Unterordnern (z. B. `archiv/`) werden aufgelistet, aber
     nicht automatisch zugeordnet; leer gewordene Altordner werden nur gemeldet, nie selbst gelöscht.
   - Den bisherigen Rufnamen des Orchestrators (oft der Name des alten Ordners) **projektweit** durch den
     neuen ersetzen — auch in Ledger, Chatlogs und Archiven.
   - Vorhandene Regeldateien mit dem Template zusammenführen. Prioritäten: **Template gewinnt** bei allem, was
     Agenten, Skills und Zusammenarbeitsregeln betrifft (projektspezifische Ergänzungen werden eingearbeitet,
     nicht verworfen); **Template-Struktur mit Projekt-Inhalt** bei den Arbeitsdateien; **das Projekt gewinnt**
     in `docs/project/` (vorhandene Projektdefinition hat Vorrang) und bei `README.md`/`.gitignore`, die nur
     ergänzt werden; **die strengere Regel gewinnt** in den Coding-Regeln — strengere Vorgaben des Templates
     werden immer übernommen.
4. **Fremde KI-Regeldateien einarbeiten.** Meldet `migrate-project.py --plan` aus Schritt 3 vorhandene
   Regeldateien anderer Werkzeuge (`.junie/guidelines.md`, `.clinerules`, `.windsurfrules`, `.cursorrules`,
   `.github/instructions/`, `AGENT.md`) in einer eigenen Kategorie: deren Inhalt nach `docs/project/
   coding_rules.md` übernehmen, soweit dort noch nicht vorhanden (bei Widersprüchen die strengere Regel),
   die Altdatei danach auf einen Verweis auf `AGENTS.md` eindampfen — nur löschen, wenn das Werkzeug sie gar
   nicht mehr braucht und {{AUFTRAGGEBER}} zustimmt. Sonst gelten zwei Regelwerke nebeneinander und laufen
   auseinander.
5. Bestand analysieren — nicht raten, am Code prüfen: Name, Stack, Struktur, Tests, Befehle, CI.
6. `AI-CONFIG.md` mit dem gefundenen IST-Zustand befüllen, dann `python .claude/scripts/create-project.py --apply`
   ausführen (ersetzt Platzhalter, entfernt nicht genutzte Werkzeug-Dateien, setzt Werte).
7. `docs/project/*` mit dem echten IST-Zustand befüllen (nicht raten), `.gitignore`-Vorschläge übernehmen.
   Die `README.md` prüfen und überarbeiten: Steht dort noch der Text der Projektvorlage („… Minimal
   Starter" o. Ä.), wird sie zu einer echten Projekt-README — was das Projekt ist, Schnellstart, Befehle,
   Struktur, Wegweiser in die Doku; der generische Vorlagentext wandert ans Ende oder fällt weg.
   **Die Arbeitsweise steht dabei oben, direkt nach der Einleitung** — für Menschen lesbar, mit der
   Konfigurationsdatei an erster Stelle (dort wird geändert, wie gearbeitet wird) und dem Board als
   Sitzungseinstieg. Was im Projekt fehlt oder rot ist, wird sichtbar genannt, nicht weggelassen.
8. **Prüf- und Testausstattung herstellen**, falls sie fehlt: die Prüfwerkzeuge des jeweiligen Stacks
   installieren und konfigurieren (bei Nuxt: ESLint, `vue-tsc`, Vitest, Playwright — siehe
   `docs/project/coding_rules.d/nuxt.md` § Werkzeuge). Kommen dabei Abhängigkeiten hinzu oder werden welche
   aktualisiert, vorher {{AUFTRAGGEBER}} fragen — das verändert ein fremdes Projekt. **Erst die Werkzeuge,
   dann größere Aufräumarbeiten:** ohne Lint, Typecheck und Tests gibt es kein Netz, das ein Paket-Update
   absichert. Die entstandenen Befehle in `AI-CONFIG.md` § Technik **und** `docs/project/testing.md`
   eintragen — sonst bleiben dort Platzhalter stehen und die CI prüft nichts.
9. **Code-Analyse (optional, Entscheidung von {{AUFTRAGGEBER}}):** Entweder vorab über `AI-CONFIG.md`
   § `Code-Analyse` (`nein` | `vorschlagen` | `fragen`) oder — beim Default `fragen` — als einzelne Rückfrage
   im Gespräch, **nachdem** `docs/project/` befüllt ist. Bei „ja": den Bestand read-only prüfen (Struktur,
   Duplikate, tote Pfade, fehlende Tests, veraltete Abhängigkeiten, Sicherheitsrisiken) und das Ergebnis
   **nur** als priorisierte Vorschläge nach `docs/ai/backlog.md` schreiben (Sicherheit zuerst, je Punkt
   Befund, Fundstelle, Vorschlag, Aufwand). Kein Code wird geändert; Umsetzung erst, wenn {{AUFTRAGGEBER}}
   einen Punkt freigibt und er als Aufgabe in `tasks.md` landet.
10. Ersten `docs/ai/board.md`-Stand und `docs/ai/ledger.md`-Eintrag schreiben, danach
   `python .claude/scripts/create-project.py --finish` ausführen.
11. Commit per Pathspec nach Freigabe.
12. `python .claude/scripts/update-template.py --graft` ausführen (nach Freigabe) — stellt per leerem
   Merge-Commit eine gemeinsame Historie mit dem Template her, ohne den Arbeitsbaum zu verändern;
   Voraussetzung für spätere `/update-template`-Läufe.
13. **Einrichtung abschließen**, sobald {{AUFTRAGGEBER}} das ausdrücklich sagt — nicht automatisch an dieser
    Stelle: einmal fragen, ob die Einrichtung abgeschlossen ist oder noch etwas kommt (Checkliste
    „Einrichtung abschließen" unten). Bei „abgeschlossen" die dortigen Schritte ausführen; bei „noch nicht"
    bleibt alles liegen, bis {{AUFTRAGGEBER}} es später auslöst.

## Einrichtung abschließen

Letzter, eigenständig ausgelöster Schritt nach „Neues Projekt" oder „Projekt nachrüsten": entfernt die
Werkzeuge, die nur zum Anlegen bzw. Nachrüsten gebraucht wurden, aus dem fertig eingerichteten Projekt. Läuft
nie automatisch am Ende der beiden Checklisten mit — {{AUFTRAGGEBER}} entscheidet, wann die Einrichtung
wirklich fertig ist. Bis dahin erinnert ein kurzer Hinweis bei jedem Sitzungsstart daran, dass der Schritt
noch offen ist.

1. **Vorbedingung:** der Arbeitsbaum muss sauber sein — eine laufende Aufgabe zuerst regulär abschließen
   (Checkliste „Aufgabe abschließen").
2. `python .claude/scripts/finish-setup.py --plan` ausführen und vollständig zeigen: was entfernt wird, was
   bewusst liegen bleibt, was inhaltlich noch offen ist.
3. Meldet der Plan noch nicht eingearbeitete fremde KI-Regeldateien, diese zuerst erledigen (siehe Checkliste
   „Projekt nachrüsten" Schritt 4) — sonst gelten zwei Regelwerke nebeneinander und laufen auseinander.
4. **Einmal nachfragen**, auch wenn {{AUFTRAGGEBER}} den Schritt selbst ausgelöst hat — er ist nicht ohne
   Weiteres rückgängig zu machen: „Einrichtung abschließen? Danach lassen sich in diesem Projekt keine neuen
   Projekte mehr anlegen/nachrüsten. a) ja b) noch nicht". Ohne Antwort **nicht** ausführen.
5. `python .claude/scripts/finish-setup.py --apply` ausführen: die Werkzeuge zum Anlegen und Nachrüsten
   selbst verschwinden aus dem Projekt, dazu die beiden Checklisten-Abschnitte „Neues Projekt" und „Projekt
   nachrüsten". Erhalten bleiben: Template-Update, die laufend wirkende `AI-CONFIG.md`, Logging sowie die
   Checklisten „Doku prüfen und nachziehen" und „Aufgabe abschließen".
6. Ergebnis verbuchen — Ledger-Eintrag „Einrichtung abgeschlossen" mit der Liste der entfernten Dateien,
   Board-Kurzbilanz nachziehen — und per Pathspec committen (Checkliste „Aufgabe abschließen").

## Template-Update

Wenn Änderungen aus dem Template (übergeordnetes Vorlagen-Repo, per Remote „template" verbunden) in ein
bereits laufendes, abgeleitetes Projekt nachgezogen werden sollen — die eingesetzten Platzhalterwerte
(Projektname, Auftraggeber, Befehle, …) und die projektspezifische Doku (`docs/project/`, `docs/ai/`-
Arbeitsdateien, README) bleiben dabei erhalten:

1. Verfügbare Änderungen abrufen (fetch) und sichten: wie viele Commits, welche Dateien betroffen.
2. Prüfen, welche der betroffenen Dateien projektspezifisch sind (bleiben unverändert) und welche die
   Template-Logik übernehmen sollen.
3. Änderungen per Merge einspielen.
4. Bei Konflikten: projektspezifische Dateien/Bereiche (siehe `keep_local` in `.claude/template.json`)
   gewinnen bei gewöhnlichen Konflikten automatisch; alle übrigen werden **inhaltlich zusammengeführt**, nie durch Wegwerfen einer Seite
   gelöst. Dazu jeweils beide Fassungen lesen und die Absicht dahinter erkennen:
   - **Beide Seiten geändert:** Template-Fassung als Gerüst, projektspezifische Zeilen (echte Werte, eigener
     Stack, zusätzliche Agenten/Skills) hineinziehen. Nur bei echtem Widerspruch entscheidet die Priorität —
     Template-Logik in `.claude/`, `AGENTS.md`, `CLAUDE.md` und den Checklisten, Projekt in `docs/project/`,
     strengere Regel bei den Coding-Regeln; der verworfene Teil wird im Journal genannt.
   - **Vom Projekt gelöscht, im Template geändert:** erst prüfen, ob die Datei im Projekt unter anderem Namen
     weiterlebt (umstrukturierter Arbeitsordner ist der Normalfall). Dann gehört die Template-Änderung in die
     neue Datei, und die alte bleibt gelöscht. Wurde die Datei dagegen bewusst entfernt, bleibt sie weg.
     Sobald ein Umbenennungs-Kandidat erkennbar ist, wird der Fall immer vorgelegt statt automatisch
     entschieden; nur ohne Kandidat und bei einer ohnehin projekteigenen Datei bleibt es automatisch bei
     „gelöscht".
   - Hat das Projekt Inhalte anders verteilt oder zusammengezogen, wandert die Änderung dorthin, wo das Thema
     im Projekt tatsächlich steht — eine gewachsene Struktur wird nicht auf das Template-Schema zurückgedreht.
   - **`docs/ai/resources.md`** (Quellensammlung zum Thema) pflegt das Template: Bei einem Konflikt gewinnt
     die Template-Fassung, nur der Abschnitt „Eigene Quellen dieses Projekts“ am Dateiende bleibt beim
     Projekt. Die Sammlung enthält Links, die veralten — deshalb ist ein Update hier die Regel, nicht die
     Ausnahme.
5. In den vom Update berührten Dateien Platzhalter durch die bereits im Projekt eingesetzten echten Werte
   ersetzen (kommt z. B. vor, wenn das Template eine neue Datei mit einem Platzhalter der Form `{{NAME}}` mitbringt).
6. Prüfen: keine verbleibenden Platzhalter außer den bekannten Fundstellen in den Checklisten/Skills selbst,
   Konfigurationsdateien weiterhin gültig, Logging weiterhin funktionsfähig.
7. Commit per Pathspec.
8. Den nachgezogenen Basis-Commit des Templates in `.claude/template.json` fortschreiben, damit das nächste
   Update wieder ab diesem Stand vergleicht.
