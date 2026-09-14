---
name: prepare
description: Einen größeren Block so vorbereiten, dass er ohne Rückfragen durchläuft - Bestand recherchieren, in Aufgaben schneiden, Startklar prüfen, alle offenen Punkte auf einmal fragen. Auslöser - "/prepare", "Feature vorbereiten", "plane das", "ich bin nachher weg", "soll durchlaufen".
---

# Block vorbereiten

Setzt die Checkliste „Block vorbereiten" aus `docs/ai/checklists.md` um. Läuft im Hauptkontext
({{ORCHESTRATOR}}), weil am Ende Fragen an {{AUFTRAGGEBER}} stehen.

**Zweck in einem Satz:** {{AUFTRAGGEBER}} beantwortet **einmal** alles, was offen ist, und der Block läuft
danach durch, ohne dass er dabeisitzen muss.

Der teuerste Fehler dieses Skills ist eine Frage, die der Code schon beantwortet. Deshalb kommt die
Recherche **vor** der Fragerunde, nicht danach.

## Ablauf

1. **Umfang abstecken** — was gehört dazu, was ausdrücklich nicht. Beides aufschreiben.
2. **Bestand recherchieren, parallel.** Mehrere `explorer` in einem Nachrichtenblock auf getrennte Fragen
   ansetzen: Was gibt es schon? Welche Dateien sind betroffen? Welche Entscheidungen stehen in
   `docs/project/decisions.md`, und widerspricht eine davon dem Vorhaben? Wo ist der Code anders, als die
   Doku behauptet? Bei fremdem oder großem Bestand vorher `python .claude/scripts/code-inventory.py` — Zahlen
   statt Vermutungen.
3. **In Aufgaben oder Stories schneiden.** Je Aufgabe: Ziel in einem Satz, prüfbare Abnahmebedingung, Schritte
   als Stichpunkte. Größeres mit eigener Begründung wird eine Story (`docs/project/stories/`), der Rest eine
   Aufgabe in `docs/ai/tasks.md`.
4. **Startklar prüfen** — die fünf Kriterien aus der Checkliste (Ziel eindeutig · Abnahme prüfbar ·
   Entscheidungen getroffen · Vorbedingungen erfüllt · Unbekanntes recherchiert). Was nicht besteht, bekommt
   eine `Offen:`-Zeile und wird **nicht** begonnen.
5. **Einen einzigen Fragenblock vorlegen.** Nummeriert, je Frage Antwortmöglichkeiten und gegebenenfalls eine
   gekennzeichnete Empfehlung, sortiert danach, wie viel sie blockieren. Dazu je Frage **eine Zeile, was
   passiert, wenn sie unbeantwortet bleibt** — das macht die Auswahl schnell. Fragen landen zusätzlich in
   `docs/ai/questions.md`, damit die Antwort auch dort verbucht werden kann.
6. **Antworten verbuchen:** ADR in `docs/project/decisions.md`, `Offen:`-Zeilen leeren, Stories auf
   `abgestimmt`. Bleibt eine Frage offen, bleibt die zugehörige Aufgabe liegen — sie wird nicht „nach bestem
   Wissen" gestartet.
7. **Reihenfolge vorlegen:** was wann läuft, was parallel geht, wo ein Zwischenstand sinnvoll ist, grobe
   Dauer. Das ist der Plan, nach dem in Abwesenheit gearbeitet wird.

## Wenn {{AUFTRAGGEBER}} weg ist

Wurde der Block ausdrücklich zum Durchlaufen freigegeben („ich bin nachher weg", „lass das durchlaufen"):

- **Die vorbereitete Reihenfolge wird abgearbeitet** — keine neue Arbeit erfinden, keinen Umfang erweitern.
- Unvorhergesehenes wird notiert und **übersprungen**, nicht abgewartet: weiter mit der nächsten Aufgabe.
- Ist alles Verbleibende blockiert, wird **angehalten**. Nicht auf Verdacht weiterbauen.
- **Unumkehrbares bleibt liegen**, auch wenn es den Block aufhält — Abwesenheit ist keine Freigabe
  (`AGENTS.md` § Tabu-Bereich, § Zugriff auf laufende Systeme).
- Journal und Aufgabenstand laufend nachziehen, nicht am Ende aus der Erinnerung. Bricht der Lauf ab, ist
  der Stand dann trotzdem vollständig.
- Beim Zurückkommen **eine** Bilanz: was fertig ist mit Belegen, was liegt und warum, gebündelte Fragen.

## Grenzen

- **Keine Frage, die eine Recherche beantwortet.** Wer fragen kann, ob eine Funktion schon existiert, kann
  auch nachsehen. Gefragt wird nur, was {{AUFTRAGGEBER}} entscheiden muss, weil es von seinem Willen abhängt.
- **Kein Code in diesem Skill.** Hier entstehen Aufgaben, Stories und Entscheidungen — gebaut wird danach.
- **Kein Plan über den Umfang hinaus.** Fällt bei der Recherche etwas Wichtiges außerhalb des Blocks auf,
  wird es ein Backlog-Punkt, keine zusätzliche Aufgabe in diesem Block.
- **Startklar wird nicht großzügig ausgelegt.** „Das klärt sich beim Machen" ist genau der Satz, der später
  zur Unterbrechung führt — und wenn niemand da ist, zum Stillstand.
