<!-- generiert von .templatedev/scripts/sync-rules.py aus ../docs/ai/checklists.md – nicht bearbeiten, Änderungen im Template -->

> Datenstand: 2026-09-17 – Status: Entwurf

# Checklisten für die Zusammenarbeit

Werkzeugneutrale Arbeitsanweisungen (gelten für jeden Assistenten, siehe `AGENTS.md`). Wolfgang kann sie
wörtlich als Anweisung geben, z. B. „Führe die Checkliste Aufgabe abschließen aus
(`docs/ai/checklists.md` § Aufgabe abschließen)". Welche zusätzliche Mechanik ein bestimmtes Werkzeug dafür anbietet (automatisierter
Aufruf, Ablauf in einer separaten Session o. Ä.), steht in der jeweiligen werkzeugspezifischen Ergänzungsdatei
(siehe `AGENTS.md` § „Werkzeugspezifische Ergänzungsdateien"), nicht in dieser Checkliste.

## Idee oder Änderungswunsch aufnehmen

Läuft, sobald Wolfgang ein neues Feature, eine Idee oder einen Änderungswunsch äußert — auch
nebenbei im Gespräch. **Nicht sofort bauen.** Zwischen „das wäre gut" und der ersten Zeile Code liegen eine
Analyse und eine Entscheidung; sonst entsteht etwas, das niemand so bestellt hat.

1. **Wortlaut festhalten.** Der Wunsch in Wolfgangs eigenen Worten, unverändert — er ist die
   Messlatte für alles Weitere. Nachfragen nur, wenn ohne die Antwort nicht einmal klar ist, worum es geht.
2. **Analysieren, nicht schätzen.** Ein Konzept in `docs/project/concepts/<thema>.md` (Format siehe README
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
6. **Priorität und Zeitpunkt festlegen.** Wolfgang nennt beides; Opus setzt **seine
   eigene** Einschätzung daneben, statt zuzustimmen. In den Backlog kommt der Mittelwert (siehe
   `docs/ai/README.md` § Backlog). **Weichen beide um mehr als eine Stufe ab, steht der Grund dafür in einer
   Zeile am Punkt** — genau dort steckt meistens eine Information, die der andere nicht hatte.
7. **Verbuchen:** Backlog-Punkt(e) mit Thema, Prioritäten, Zeitpunkt, Aufwand und Verweis auf Konzept und
   ADR. Aufgaben in `docs/ai/tasks.md` entstehen **nur für das, was jetzt gemacht wird** — der Rest bleibt
   im Backlog, bis sein Zeitpunkt kommt.

**Abkürzung erlaubt, aber benannt:** Ist der Wunsch klein und eindeutig (ein Tippfehler, ein Feldname, eine
Zeile Konfiguration), entfallen Konzept und ADR — er wird direkt Aufgabe oder Backlog-Punkt. Die Abkürzung
wird ausgesprochen („mache ich direkt als Aufgabe, kein Konzept"), damit Wolfgang widersprechen kann.
Im Zweifel für die Analyse: Ein überflüssiges Konzept kostet eine halbe Stunde, ein übersehener Widerspruch
zu einer Entscheidung kostet den Umbau.

## Block vorbereiten

Läuft **vor** einem größeren Vorhaben — einem Feature, einem Umbau, einer Welle von Aufgaben. Zweck: Der
Block soll danach **ohne Rückfragen durchlaufen**. Wolfgang beantwortet alles **einmal**, in einem
Zug, und ist danach nicht mehr gebunden.

Die Vorbereitung kostet Zeit und spart mehr, als sie kostet: Eine Frage, die vorher geklärt ist, kostet
Sekunden. Dieselbe Frage mitten in der Umsetzung kostet den Faden — und wenn niemand da ist, der sie
beantwortet, kostet sie den ganzen Lauf.

1. **Umfang abstecken.** Was gehört zum Block, was ausdrücklich nicht. Das „nicht" wird aufgeschrieben, sonst
   wächst der Block während der Arbeit.
2. **Bestand recherchieren, bevor geplant wird.** Was existiert schon, welche Dateien werden angefasst,
   welche Entscheidungen sind bereits getroffen (`docs/project/decisions.md`) und welche davon widersprechen
   dem Vorhaben. Unabhängige Recherchen parallel. **Ohne diesen Schritt entstehen Fragen, die der Code
   längst beantwortet** — und genau die nerven Wolfgang zu Recht.
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
   sinnvoll ist. Damit weiß Wolfgang, was in seiner Abwesenheit passiert.

**Unbeaufsichtigter Lauf.** Sagt Wolfgang, dass er weg ist, gilt zusätzlich:

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
   vorgelegt und erst nach der Zusage von Wolfgang ausgeführt (`--apply --yes`). **Keine
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
   Aufgaben unter „nur für Wolfgang" nur auf dessen Meldung hin abhaken; Antworten in deren
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
7. **Bilanz an Wolfgang:** Ergebnis zuerst, Belege (Hash, Zahlen), offene Punkte und Fragen mit
   Nummern — **gebündelt**. Was während der Umsetzung aufgetaucht ist, wurde unterwegs in `questions.md`
   bzw. `tasks.md` abgelegt statt sofort erfragt; hier kommt es zusammengefasst auf den Tisch, zusammen mit
   jeder Annahme, unter der weitergearbeitet wurde.
8. **Ist etwas entstanden, das auch anderen hilft?** Eine neue Regel, ein Script, ein Skill, ein Ablauf,
   der sich bewährt hat — und ist die Rückmeldung eingeschaltet (`AGENTS.md` § „Freiwillige Rückmeldung"),
   dann jetzt einen Eintrag ablegen: `python .claude/scripts/feedback.py --add …`. Maßstab: Hilft es jemandem,
   der dieses Projekt nie sehen wird? Das **Muster**, nicht der Fall. Gesendet wird gesammelt, höchstens
   einmal je Woche; ist die Rückmeldung aus, entfällt der Schritt ersatzlos.
   Davon unberührt: Wolfgang kann jederzeit selbst einen Satz schicken — „Feedback: <Text>",
   „Schicke Feedback <Text>" oder `/act-feedback <Text>`. Das geht auch bei ausgeschalteter Rückmeldung und
   dann anonym, ohne Projekt-Kennung.
9. **Logging** (falls eingeschaltet, `AGENTS.md` § Logging): Commit als
   `[orchestrator] [commit] <hash> <message>` schreiben — das Log ist Mitschnitt, kein Ersatz für Journal
   oder Beleg.
10. **Kontext freigeben:** Der Detailkontext der erledigten Aufgabe wird nicht mehr gebraucht, der Stand liegt
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

### Wenn zwei Aufträge dieselbe Datei ändern

**Nur-lesende Aufträge sind nicht gemeint** — Recherche auf denselben Dateien läuft beliebig parallel und ist
der Normalfall. Es geht ums Schreiben.

Zwei Worker, die gleichzeitig dieselbe Datei schreiben, sind kein Zeitgewinn: Man tauscht Wartezeit gegen zwei
auseinanderlaufende Fassungen, die danach jemand zusammenführen muss — und das Zusammenführen kostet wieder
den Orchestrator. **Ein getrennter Arbeitsbaum (`git worktree`) hilft hier nicht**, er trennt nur die Platte,
nicht die Absicht.

In dieser Reihenfolge lösen:

1. **Aufträge nach Datei schneiden, nicht nach Thema.** Zwei Worker am selben Thema landen zwangsläufig in
   derselben Datei; zwei Worker mit je eigenen Dateien nie.
2. **Was in derselben Datei zusammengehört, ist ein Auftrag**, nicht zwei.
3. **Reihenfolge statt Gleichzeitigkeit:** erst ein kurzer Lauf, der Schnittstelle oder Signatur festlegt,
   danach parallel die Aufrufer in verschiedenen Dateien.
4. **Wird dieselbe Datei zum zweiten Mal zum Engpass, ist nicht die Delegation das Problem, sondern die
   Datei.** Dann wird sie nicht still weiter umgangen: Der Orchestrator legt eine **Frage** in
   `docs/ai/questions.md` an (aufteilen, kürzen oder so lassen? mit Empfehlung) und — sobald entschieden —
   eine **Aufgabe im Backlog** (`docs/ai/backlog.md`), die Datei zu entflechten. Beleg für die Dringlichkeit
   sind die Fälle, in denen sie den Weg versperrt hat, nicht ihre Zeilenzahl allein.

**Ein eigener Arbeitsbaum lohnt trotzdem** — nur aus anderen Gründen: ein langer, riskanter Umbau, der den
Hauptbaum lauffähig lassen soll; ein Testlauf, der keine halbfertigen Dateien sehen darf; gleichzeitige
Git-Operationen, die sich sonst am Index blockieren. Der Preis ist ein vollständiger Checkout **ohne**
Abhängigkeiten (`node_modules`, `.venv`, Build-Cache fehlen) — bei kurzen Aufträgen frisst das Einrichten den
Gewinn auf. Mechanik in Claude Code: `CLAUDE.md` § 1.

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
  gehört woandershin — Konzepte und Analysen nach `docs/project/concepts/`, abgegrenzte Vorhaben nach
  `docs/project/stories/`, Entscheidungen nach `docs/project/decisions.md`.
- **Vorlagenreste:** Kopfzeilen, die noch „Status: Entwurf" tragen, obwohl die
  Datei längst Projektinhalt hat, oder ein Statuswort außerhalb des Vokabulars in `docs/README.md`
  § Konventionen.

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
   gelöst. Ist die Einrichtung bereits abgeschlossen (`setup_complete`), verwirft ein Konflikt zusätzlich
   automatisch die Template-Seite genau der Abschnitte, die `/act-finalize` aus diesem Projekt entfernt hat
   (Einrichtungs-Scripte/-Skills, die Setup-Checklisten, `template-only`-Blöcke in `AGENTS.md`/`CLAUDE.md`) —
   gemeldet, nicht still. Dazu jeweils beide Fassungen lesen und die Absicht dahinter erkennen:
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
7. **Sonderfall `docs/project/konzepte/`:** Der Ordner steht unter `keep_local` und wird beim Merge deshalb
   nie automatisch umbenannt. Existiert er im Projekt noch (statt `docs/project/concepts/`), wird
   vorgeschlagen, ihn per `git mv docs/project/konzepte docs/project/concepts` umzuziehen und alle Verweise
   darauf nachzuziehen — nur nach Zustimmung von Wolfgang.
8. Commit per Pathspec — sobald keine Konflikte mehr offen sind, sofort committen oder ausdrücklich fragen,
   ob der Merge bewusst offen bleiben soll. Ein gestagter, nie committeter Merge bleibt sonst unbemerkt
   liegen; `--check`/`--status` warnen zwar beim nächsten Sitzungsstart, das ist aber der Notnagel.
9. Den nachgezogenen Basis-Commit des Templates in `.claude/template.json` fortschreiben, damit das nächste
   Update wieder ab diesem Stand vergleicht.
