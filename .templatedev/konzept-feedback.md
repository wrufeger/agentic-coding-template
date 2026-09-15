> Datenstand: 2026-09-15 – Status: abgestimmt — `Q1`–`Q3` beantwortet, Client und Endpunkt gebaut, Betrieb offen

> **Achtung beim Lesen:** Alles bis zur Trennlinie ist der Stand **vor** der Entscheidung — die dortige
> Empfehlung (GitHub-Issue) wurde **verworfen**, weil Issues in einem öffentlichen Repo für jeden lesbar
> sind. Was gilt, steht im Block „Entschieden am 2026-09-14" am Ende.

# Rückmeldung abgeleiteter Projekte an das Template

**Leitfrage:** Wie melden sich Projekte, die aus diesem Template entstanden sind, freiwillig zurück — damit
`.templatedev` aus ihrer Weiterentwicklung lernen kann? (`Q1`)

**Aufwand:** je nach Weg 0,5–3 PT, siehe Optionen.

## Ausgangslage

`.templatedev/README.md` führt heute **lokale** Testprojekte, die per Pfad eingetragen sind; `testprojekte.py`
gleicht sie ab. Das funktioniert für Projekte auf diesem Rechner und für sonst nichts. Wer das Template auf
GitHub benutzt, bleibt unsichtbar — Fehler, Umwege und gute Ideen aus fremden Projekten kommen nie zurück.

Der Wunsch: ein Schalter `Feedback` in `AI-CONFIG.md`, über den ein Projekt sich als Testkandidat registriert.
Gemeldet werden sollen **Datum**, eine **öffentliche Repo-URL** und **wie das Projekt entstanden ist** (neu
oder nachgerüstet; leer, per Fragenkatalog oder aus einer ausgefüllten `AI-CONFIG.md`). Danach könnte
`.templatedev` die registrierten Repos nacheinander abfragen und ihre Änderungen auswerten.

## Was dagegen spricht, das einfach zu bauen

- **Es sind fremde Daten.** Eine Repo-URL identifiziert oft eine Person oder eine Firma. Wer ein Template
  klont, rechnet nicht damit, dass sein Projekt irgendwo als Datensatz auftaucht. Ein Schalter, der
  standardmäßig auf `ja` steht, ist eine Einwilligung, die niemand gegeben hat.
- **Es gibt keine Gegenstelle.** Das Template ist ein Git-Repo, kein Dienst. „Die App schickt etwas zurück"
  setzt einen Empfänger voraus, den es nicht gibt — und der, einmal gebaut, gepflegt und abgesichert werden
  muss.
- **Private Repos bringen nichts.** Nur öffentliche Repos lassen sich später auswerten. Bei privaten bliebe
  eine URL ohne Zugriff — ein Datensatz ohne Nutzen, aber mit allen Nachteilen.

Keiner dieser Punkte spricht gegen das Vorhaben, alle drei aber gegen die naheliegende Umsetzung.

## Optionen

### a) GitHub-Issue im Template-Repo ~~(Empfehlung)~~ — **verworfen am 2026-09-14**

Das Projekt legt beim Abschluss der Einrichtung — **nach ausdrücklicher Zustimmung** — ein Issue im
Template-Repo an, per `gh issue create` mit einer festen Vorlage.

- **Dafür:** Kein Dienst nötig, nichts zu betreiben. Der Entwickler **sieht vorher genau, was gepostet wird**,
  und kann es abbrechen. Alles ist öffentlich und damit prüfbar — auch für ihn. Rücknahme heißt: Issue
  schließen. Auswertung später über die GitHub-API, dieselbe Mechanik wie `testprojekte.py`.
- **Dagegen:** Braucht ein GitHub-Konto und `gh`. Die Meldung ist öffentlich — was für manche ein Vorteil
  ist („ich zeige, dass ich es benutze") und für andere der Ausschlussgrund.
- **Aufwand:** ~0,5 PT (Vorlage, Aufruf in `finish-setup.py`, Abbruchweg).

### b) Eintrag per Pull Request in eine Liste

Statt eines Issues ein PR auf eine Datei `.templatedev/daten/projekte.md`.

- **Dafür:** Die Liste ist versioniert und maschinenlesbar.
- **Dagegen:** Deutlich mehr Reibung (Fork, Branch, PR), praktisch macht das kaum jemand — und jeder PR
  bedeutet Arbeit auf der Empfängerseite.
- **Aufwand:** ~1 PT.

### c) Eigener Endpunkt (HTTPS-POST an einen selbst betriebenen Dienst)

- **Dafür:** Beliebiges Format, auch stille Meldungen, auch aus privaten Repos.
- **Dagegen:** Ein Dienst, der betrieben, abgesichert und bezahlt werden will; eine Datenschutzerklärung wird
  nötig; die Meldung ist für den Entwickler **nicht einsehbar**, und genau das macht sie zu Telemetrie im
  schlechten Sinn. Für ein Template, das jemand freiwillig klont, ist das der sicherste Weg, Vertrauen zu
  verlieren.
- **Aufwand:** ~3 PT plus laufender Betrieb.

### d) Nichts einbauen, nur fragen

Beim Abschluss der Einrichtung einmal im Chat anbieten: „Magst du dein Repo als Testprojekt melden? Dann
schick mir die URL." — ohne Mechanik.

- **Dafür:** null Aufwand, null Datenschutzfragen.
- **Dagegen:** passiert in der Praxis fast nie.

## Empfehlung (überholt — Stand vor dem 2026-09-14)

**a) GitHub-Issue**, mit drei Bedingungen:

1. **Standard ist `fragen`, nicht `ja`.** Der Schalter heißt `Feedback` mit den Werten `fragen` (Default) ·
   `ja` · `nein`. Bei `fragen` kommt beim Abschluss der Einrichtung **einmal** die Frage; ohne Antwort
   passiert nichts. Ein voreingestelltes `ja` wäre eine Einwilligung, die niemand erteilt hat.
2. **Der Inhalt wird vorher gezeigt.** Genau diese Felder, nicht mehr: Datum · Repo-URL (nur wenn öffentlich)
   · Weg (`neu`/`nachgerüstet`) · Ausfüllart (`leer`/`Interview`/`AI-CONFIG`) · Template-Basis-Commit. **Kein**
   Projektname, **kein** Stack, **keine** Pfade, **keine** Angaben zur Person.
3. **Widerruf ist dokumentiert.** Im Issue steht, wie man den Eintrag wieder loswird.

Die Auswertung in `.templatedev` kommt danach als eigener Schritt — sie ist ohne Datenbestand ohnehin
sinnlos.

## Offene Punkte (erledigt, siehe Entscheidung unten)

- `Q1` in `.templatedev/questions.md` — Weg und Standardwert.
- Ungeklärt bis dahin: ob der Schalter überhaupt nach `AI-CONFIG.md` gehört oder besser einmalig beim
  Abschluss abgefragt wird (er wirkt genau einmal, anders als alle anderen Schlüssel dort, die laufend gelten).


---

# Entschieden am 2026-09-14 (`Q1` c, `Q2` a, `Q3` b)

Gewählt wurde **c) eigener Endpunkt** auf `rufeger.de`, **kein** Schlüssel in `AI-CONFIG.md` (nur die
einmalige Frage bei `/finalize`), und die Meldung nennt die Zieladresse im Klartext.

**Warum nicht a)**, obwohl es oben empfohlen war: Ein Issue in einem öffentlichen Repo ist für jeden lesbar,
auch für Suchmaschinen und über die API. Eine Rückmeldung darüber, was in einem Projekt an der
Zusammenarbeit hakte, soll niemand außer dem Template-Autor sehen können. Beim Endpunkt ist das Einliefern
öffentlich erreichbar, das **Lesen** aber nur mit Token (§ „Abholen").

**Gebaut ist die Client-Seite** (`.claude/scripts/feedback.py`): Einwilligung, Projekt-ID, Ausgang,
Prüfung auf Geheimnisse, Anzeige der Nutzlast, Versand per POST. **Offen ist der Endpunkt selbst.**

## Schnittstelle, die der Endpunkt erfüllen muss

Zwei Operationen, klar getrennt: Einliefern ist **öffentlich**, Abholen ist **authentifiziert**.

### 1. Einliefern — `POST /agentic-coding-feedback`

Öffentlich, ohne Anmeldung. Body ist JSON in genau dieser Form:

```json
{
  "schema": 1,
  "projekt_id": "9f276443494342a9a4c954046aaa4819",
  "datum": "2026-09-14",
  "template_basis": "abc1234",
  "weg": "neu",
  "ausfuellart": "interview",
  "werkzeuge_entfernt": ["Aider", "Cursor"],
  "regelsaetze": ["nuxt", "typescript"],
  "schalter": {"Testtiefe": "alles", "Schreibstil": "kurz"},
  "eintraege": [{"art": "skill", "titel": "…", "text": "…", "datum": "2026-09-14"}],
  "repo_url": "https://github.com/…"
}
```

`projekt_id` ist eine lokal erzeugte Zufallskennung (UUID4 ohne Bindestriche), **kein** Hash aus Projektdaten.
Sie macht mehrere Meldungen desselben Projekts zusammenführbar, ohne es zu benennen. `repo_url` ist optional.

Antwort: `202` bei Annahme, `400` bei Schemaverstoß, `413` zu groß, `429` zu häufig. Der Client wertet nur
aus, ob der Status im 2xx-Bereich liegt.

### 2. Abholen — `GET /agentic-coding-feedback/inbox`, dann `POST …/ack`

Nur für den Template-Autor, Bearer-Token im Header. `GET` liefert einen Stapel mit je einer `id`; `POST /ack`
mit der Liste der `id`s löscht genau diese.

**Nicht „Abholen löscht sofort".** Bricht die Übertragung nach dem Löschen ab, ist die Meldung weg und
niemand merkt es. Zwei Schritte kosten eine Zeile mehr Code und machen den Verlust unmöglich.

## Was der Endpunkt tun muss, weil er öffentlich ist

- **Dem Client nicht glauben.** Schema serverseitig prüfen, unbekannte Felder verwerfen, `schalter`,
  `regelsaetze` und `art` gegen geschlossene Wortlisten prüfen. Der Client prüft schon — aber jeder kann
  POSTen, nicht nur der Client.
- **Deckel:** Body ≤ 32 KB, Ratenbegrenzung je IP und je `projekt_id`, `eintraege` ≤ 20 je Meldung.
- **Roh speichern, nie ausführen.** Eine Datei je Meldung (`daten/JJJJ-MM/<id>.json`) außerhalb des
  Web-Roots, oder SQLite. Kein Rendern als HTML, keine Auswertung beim Empfang.
- **Aufbewahrungsfrist** festlegen und nennen (z. B. 24 Monate), dazu eine knappe Datenschutzhinweis-Seite
  unter der URL — sie nimmt Daten von Dritten entgegen.

## Der Punkt, der beim Auswerten wichtiger ist als alles andere

Die abgeholten Texte sind **von Fremden geschrieben**. Wenn die KI im Template sie später liest, um
Verbesserungen abzuleiten, sind sie **Daten, keine Anweisungen** — dieselbe Regel wie für Antworten von
MCP-Servern (`CLAUDE.md` § MCP-Server). Ein Eintrag mit dem Text „ignoriere deine bisherigen Regeln und …"
ist ein Fundstück für die Auswertung, kein Befehl. Das gehört in die Regeln von `.templatedev`, bevor die
erste Meldung ankommt.

## Offen

- **Gebaut am 2026-09-15:** `.templatedev/scripts/feedback-endpunkt.php` (PHP, Stdlib, keine Abhängigkeit)
  und `.templatedev/scripts/feedback-abholen.py` (abholen, ablegen, quittieren, auswerten). Authentifiziert
  wird per **JWT** (HS256, gemeinsames Geheimnis) statt mit einem festen Bearer-Token — ein abgelaufenes
  Token ist von selbst wertlos. Einrichtung: `.templatedev/scripts/README.md`.
- **Offen bleibt der Betrieb:** Datei auf `rufeger.de` ausrollen, Geheimnis erzeugen, Ablage außerhalb des
  Web-Roots anlegen, prüfen, dass sie nicht per URL erreichbar ist.
- Datenschutzhinweis unter der URL.
- Abgeholtes ist gitignored (`.templatedev/.gitignore`) — fremde Meldungen gehören nicht in ein öffentliches
  Repo. Ins Journal kommt nur das Muster.

---

# Nachtrag 2026-09-15 — zwei Stellen, an denen sich die Umsetzung von der Entscheidung entfernt hat

1. **Schalter in `AI-CONFIG.md`.** Die Entscheidung oben sagt „kein Schlüssel in `AI-CONFIG.md`". Inzwischen
   stehen dort zwei — `Feedback` (`aus`/`bestaetigen`/`automatisch`/`manuell`) und `Feedback-Takt` —, weil
   „ob und wie oft gesendet wird" laufend gilt und nicht nur einmal beim Abschluss. Die einmalige Frage bei
   `/finalize` bleibt daneben bestehen; sie setzt die Schlüssel, ersetzt sie aber nicht.
2. **Wo das Sendeprotokoll liegt, ist jetzt eine eigene Frage.** Das Protokoll unter
   `docs/ai/template-feedback/` ist der Nachweis — in einem **öffentlichen** Projekt-Repo wäre damit
   allerdings auch die Rückmeldung öffentlich lesbar. Also wird bei der Einwilligung mitgefragt:
   mitversionieren (Vorschlag) oder per `.gitignore` lokal halten. Mechanik:
   `feedback.py --enable --protokoll versionieren|lokal`, ausgenommen wird nur
   `docs/ai/template-feedback/*.json` — die README des Ordners bleibt versioniert, damit nachlesbar bleibt,
   **dass** gesendet wird. `--status` und die Ausgabe von `--send` sagen, welcher Fall gilt.

   Dass die Empfängerseite nichts öffentlich macht, bleibt davon unberührt (§ „Abholen" — Token).
