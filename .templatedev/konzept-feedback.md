> Datenstand: 2026-09-14 – Status: Entwurf — Entscheidung offen (`Q1`)

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

### a) GitHub-Issue im Template-Repo (Empfehlung)

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

## Empfehlung

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

## Offene Punkte

- `Q1` in `.templatedev/questions.md` — Weg und Standardwert.
- Ungeklärt bis dahin: ob der Schalter überhaupt nach `AI-CONFIG.md` gehört oder besser einmalig beim
  Abschluss abgefragt wird (er wirkt genau einmal, anders als alle anderen Schlüssel dort, die laufend gelten).
