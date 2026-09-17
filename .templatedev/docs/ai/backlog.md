> Datenstand: 2026-09-17 – Status: aktuell

# Backlog — Template-Entwicklung

1. Nummern `B<n>` aufsteigend und stabil (nie neu vergeben).
2. Status: `[ ]` offen, `[x]` erledigt.
3. Prio: `hoch` · `mittel` · `niedrig` · `offen`.
4. Je Tabelle stehen die wichtigsten offenen Punkte oben, erledigte immer unten.
5. Eine Entscheidung des Auftraggebers („machen", „später", „nein, weil …") steht am Anfang der Info-Spalte.

## Template-Update und Einrichtung

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B28 | niedrig | Widerspruch bei no_replace | Machen: `no_replace` widerspricht sich zwischen `AGENTS.md`, `template.json` und `checklists.md` — erst klären, welche Fassung gilt. [Details](#b28) |
| [x] | B48 | mittel | `/act` zeigt nur passende Befehle | Erledigt 2026-09-17: `/act` filtert per Frontmatter `phase` (`setup`/`project`/`maintenance`) nach Repo-Stand, `/act all` zeigt alles. [Details](#b48) |
| [x] | B51 | mittel | Frischer Klon erklärt sich selbst | Erledigt 2026-09-17: Hook `template-welcome.py` gibt dem Modell im frischen Klon Kontext (kein Blockieren), Marker `.templatedev/.maintainer`; beim Anlegen/Nachrüsten entfernt. [Details](#b51) |
| [x] | B36 | hoch | Template-Update bleibt halber Merge | Erledigt 2026-09-17: Warnung bei offenem Template-Merge (`--check`/`--status`), `--continue` nimmt `MERGE_HEAD`, Skill verlangt Commit oder Rückfrage. [Details](#b36) |
| [x] | B38 | mittel | Update bringt entfernte Abschnitte zurück | Erledigt 2026-09-17: bei `setup_complete` bleiben entfernte Scripte und Setup-Abschnitte draußen; Pfade aus dem Template-Ref nur statisch gelesen, kein fremder Code. [Details](#b38) |
| [x] | B1 | offen | Feldweiser Merge von template.json | 2026-09-13: `template.json` wird feldweise gemergt (`update-template.py`). |
| [x] | B2 | offen | Enge Permissions für Update/Abschluss | 2026-09-13: Permissions eng gefasst — `--apply`/`--finish` fragen nach, `git fetch template` exakt (`settings.json`). |
| [x] | B3 | offen | CRLF bei Platzhalter-Ersetzung | 2026-09-13: Platzhalter-Ersetzung erhält CRLF-Unterstützung (`update-template.py`). |
| [x] | B8 | offen | Hook-Entfernung nur Template-Hooks | 2026-09-13: Hook-Entfernung trifft nur die vom Template gesetzten Hooks (`create-project.py`). |
| [x] | B10 | offen | Gitignorierte Dateien werden gemeldet | 2026-09-13: Gitignorierte Dateien werden gemeldet statt verschoben (`migrate-project.py`). |
| [x] | B11 | offen | Namensersetzung schont Code/URLs | 2026-09-13: Namensersetzung lässt Code-Blöcke und URLs aus (`migrate-project.py`). |
| [x] | B12 | offen | Beidseitige Umbenennung erkannt | 2026-09-13: Umbenennung auf beiden Seiten wird erkannt (`update-template.py --conflicts`). |
| [x] | B14 | offen | Tote Konstante entfernt | 2026-09-13: Tote Konstante `PRIORITY_RULES` entfernt (`update-template.py`). |
| [x] | B15 | offen | Mehr Merge-Kandidaten bei Nachrüstung | 2026-09-13: Merge-Kandidaten um Werkzeug-Verweisdateien ergänzt (`migrate-project.py`). |
| [x] | B16 | offen | Vorschau vor Rufnamen-Umbenennung | 2026-09-13: Rufnamen-Umbenennung zeigt vorher eine Zeilen-Trefferliste, Schreiben erst mit `--yes` (`rename-lib.py`). |
| [x] | B17 | offen | Restplatzhalter-Meldung präzisiert | 2026-09-13: Restplatzhalter-Meldung trifft nur noch echte Marken, nicht Vue-Mustache (`setup-lib.py`). |
| [x] | B18 | offen | Fremde KI-Regeldateien erkannt | 2026-09-13: Fremde KI-Regeldateien werden erkannt und als eigene Kategorie gemeldet (`rename-lib.py`). |
| [x] | B19 | offen | Einrichtung wird abgeschlossen | 2026-09-13: Einrichtung wird abgeschlossen statt liegengelassen (`finish-setup.py`, Skill `/finalize`, SessionStart-Erinnerung). [Details](#b19) |
| [x] | B20 | offen | Fremde Regeldateien eingearbeitet | 2026-09-13: Fremde Regeldateien werden eingearbeitet und auf einen Verweis eingedampft (Checkliste, `/apply-template`, `finish-setup.py`). |
| [x] | B21 | offen | template_only-Liste für Merge-Ausschluss | 2026-09-13: Dritte Liste `template_only` verhindert Merge von `.templatedev.md`/`.github/README.md` ins Projekt. [Details](#b21) |
| [x] | B26 | offen | README des Zielprojekts überarbeiten | 2026-09-14: README-Regel verlangt jetzt Prüfen statt bloßem Ergänzen, mit Aufbau-Vorgabe, AI-CONFIG.md an erster Stelle. [Details](#b26) |
| [x] | B31 | offen | Abgewählte Pfade beim Update | 2026-09-15: Abgewählte Pfade (Wartung/Optimierung/KI-Werkzeuge) werden beim Update wie `template_only` behandelt. [Details](#b31) |

## Konfiguration (AI-CONFIG.md)

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B27 | mittel | Mehrsprachigkeit des Templates konzipieren | Entschieden 2026-09-17 (Wolfgang): Schlüssel `Sprache` vorerst entfernt, Deutsch ist Standard; Ideensammlung für ein späteres Konzept. [Details](#b27) |
| [x] | B43 | hoch | `sync-config.py --apply` bricht ab | Erledigt 2026-09-17: `import time` ergänzt, Import-Check über alle Scripte. [Details](#b43) |
| [x] | B37 | hoch | Neue AI-CONFIG-Schlüssel gehen verloren | Erledigt 2026-09-17: fehlende Schlüssel werden in `sync-config.py` und nach dem Update ergänzt; verschobene Schlüssel/fehlende Tabellen nur als Hinweis, Hook bleibt still. [Details](#b37) |
| [x] | B41 | niedrig | Erläuterungen aus AI-CONFIG.md auslagern | Erledigt 2026-09-17: Erläuterungen nach `docs/ai/config-guide.md`, in `AI-CONFIG.md` Verweise. [Details](#b41) |
| [x] | B4 | offen | Ablageort Wartungsberichte wählbar | 2026-09-13: Ablageort der Wartungsberichte per `AI-CONFIG.md` wählbar (`create-project.py`). |

## Rückmeldung (Feedback)

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B29 | offen | Rückmeldung abgeleiteter Projekte | In Arbeit: Abgeleitete Projekte melden sich freiwillig als Testkandidat, damit `.templatedev` ihre Weiterentwicklung auswerten kann. [Details](#b29) |
| [ ] | B32 | offen | Feedback neu bearbeiten | Umgesetzt bis auf Endpunkt-Inbetriebnahme: Feedback-Umfang/-Takt/-Bestätigung neu gebaut; offen bleibt Rollout auf `rufeger.de`. [Details](#b32) |
| [x] | B39 | mittel | Feedback-Ablage nach Versand widersprüchlich | Erledigt 2026-09-17: Protokolle unter `sent/protocols/` (Altbestand migriert, lokal-Wahl bleibt), Sofortversand bei automatisch+sofort, Abschnitt „Von dir bereits gesendet“. [Details](#b39) |

## Integrationen/MCP und Design

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B25 | mittel | MCP-Auswahl automatisch einrichten | Machen: MCP-Auswahl aus `AI-CONFIG.md` § `MCP-Server` wird nicht automatisch eingerichtet — `sync-config.py` soll `.mcp.json` selbst pflegen. [Details](#b25) |
| [ ] | B34 | offen | Issue-Tracker ohne Git anbinden | Später: `/issue`/`/integrations` bauen zunächst nur GitLab/GitHub (Q11); danach MCP (`atlassian`, `linear`), YouTrack fehlt im Katalog. [Details](#b34) |
| [x] | B23 | offen | Design-Wege über /design hinaus | 2026-09-14: Design-Wege über `/design` hinaus recherchiert, in `CLAUDE.md` § 5 als Tabelle aufgenommen; teils überholt durch B24. [Details](#b23) |
| [x] | B24 | offen | Design-Schalter raus, MCP-Katalog rein | 2026-09-14: Design-Schalter zurückgebaut, stattdessen `.claude/mcp-katalog.md` (21 Server) und drei Design-Skills. [Details](#b24) |

## Doku und Formregeln

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B33 | offen | Aufgaben erst eintragen, wenn ausführbar | Machen: Aufgaben im Tabu-Bereich erst eintragen, wenn alle Voraussetzungen erfüllt sind (Code gepusht, Fragen beantwortet). [Details](#b33) |
| [x] | B40 | mittel | Formatregel für Fragen rendert falsch | Erledigt 2026-09-17: Frage fett als Absatz, Optionen als Liste, Leerzeilen; `.templatedev/docs/ai/questions.md` seit T5 im neuen Format. [Details](#b40) |
| [x] | B5 | offen | Fußnoten-Konvention Datenstände | 2026-09-13: Fußnoten-Konvention für fehlende Datenstände eingeführt (`docs/README.md`). |
| [x] | B6 | offen | Incident als Einzeldatei | 2026-09-13: Incident-Schema als Einzeldatei beschrieben (`docs/project/incidents/README.md`). |

## Template-Pflege/Werkzeuge

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B46 | niedrig | Hooks: Interpreter-Probe je Aufruf kostet Zeit | Neu (Review): jeder Hook startet Python zweimal; Probe je Sitzung zwischenspeichern, falls Latenz stört. [Details](#b46) |
| [ ] | B47 | niedrig | Hooks führen ungeprüfte Merge-Fassung aus | Neu (Review): Hooks starten Scripte aus dem Arbeitsbaum, auch eine gemergte, noch nicht committete Fassung; Restrisiko bei nicht erkanntem `MERGE_HEAD`. [Details](#b47) |
| [ ] | B52 | niedrig | Restrisiken Pflege-Projekt prüfen | Neu (Review T5): `claudeMdExcludes` mit Laufwerksbuchstaben, Skill-Suche im Monorepo, Sub-Agenten aus dem Root in `.templatedev/` erneut belegen. [Details](#b52) |
| [x] | B22 | hoch | Erkenntnisse aus bandliste prüfen | Erledigt 2026-09-17: 6 Kandidaten aus `bandliste` — Ersetzung ohne `node_modules`/Build-Ordner (versionierte + neue nicht ignorierte Dateien), Kodierungsregel in `AGENTS.md`, 4 Regelbausteine Nuxt/Vue; Rest rein fachlich. [Details](#b22) |
| [x] | B42 | niedrig | Warnung vor bewusst gehaltenen Altnamen | Erledigt 2026-09-17: `LEGACY_REMOVE_PATHS` in `setup-lib.py`, Selbstprüfung überspringt sie. [Details](#b42) |
| [x] | B7 | offen | Atomares Schreiben von Statusdateien | 2026-09-13: `status.json`/`template.json` werden atomar geschrieben (`maintenance-check.py`, `update-template.py`, `setup-lib.py`). |
| [x] | B9 | offen | Leere Argumente brechen ab | 2026-09-13: Leere Argumente brechen mit Exit 2 ab (`maintenance-check.py`). |
| [x] | B13 | offen | UTF-8-Ausgabe in allen Scripten | 2026-09-13: UTF-8-Ausgabe in allen sieben Scripten eingeführt. |
| [x] | B30 | offen | Löschen trifft nie ungesicherte Dateien | 2026-09-15: Löschen prüft vorher `git status`; gitignorierte/ungetrackte/geänderte Pfade bleiben liegen und werden gemeldet. [Details](#b30) |
| [x] | B44 | mittel | Python als Voraussetzung, Hooks ohne Python | Erledigt 2026-09-17: README § Voraussetzungen (3.9+), Prüf-Hook beim Sitzungsstart, alle Hooks wählen den Interpreter per Probe (Store-Platzhalter). [Details](#b44) |
| [x] | B45 | mittel | Pfade außerhalb des Projekts plattformgerecht | Erledigt 2026-09-17: Regel in `AGENTS.md`/`CLAUDE.md` § 4, Beispielpfade neutral, `~` erklärt. [Details](#b45) |

## Neue Skills

| | Nr | Prio | Titel | Info |
| :-: | :-- | :-- | :-- | :-- |
| [ ] | B49 | offen | Skill `act-check-translations` | Idee (Wolfgang): Mehrsprachigkeit erkennen, Sprachdateien auf Vollständigkeit prüfen; `extended` per Playwright im Browser. Vorschlag mittel. [Details](#b49) |
| [ ] | B50 | offen | Skill `act-seo` | Idee (Wolfgang): SEO-Prüfung im Code (Head, Überschriften, SSR/SSG, Links, Duplikate, `lang`); live Google/Search Console nur bei `live: ja`. Vorschlag mittel. [Details](#b50) |

## Details

<a id="b19"></a>
### B19 · Einrichtung wird abgeschlossen statt liegengelassen

- erledigt 2026-09-13 (2. Runde)
- `finish-setup.py`, Skill `/finalize`, SessionStart-Erinnerung
- Bibliothekstrennung `setup-lib.py`/`rename-lib.py`

<a id="b21"></a>
### B21 · template_only-Liste verhindert Merge von .templatedev.md/.github/README.md

- erledigt 2026-09-13 (3. Runde)
- dritte Liste `template_only` neben `keep_local`/`no_replace` (`update-template.py`, `template.json`)
- gefunden beim ersten echten `/update-template` an einem Fremdprojekt — der Weg war bis dahin nie unter realen Bedingungen gelaufen

<a id="b22"></a>
### B22 · Erkenntnisse aus bandliste auf Template-Relevanz prüfen

- angelegt 2026-09-14, Priorität hoch
- Kernzweck dieser Ablage — bisher nie systematisch gelaufen
<!-- check-refs:ignore -->
- im Weg-2-Testprojekt sind an einem Tag 26 beantwortete Fragen und ADR-7 bis ADR-32 entstanden, dazu ein Backlog mit über 50 Punkten (diese Nummern gehören zum Testprojekt, nicht zu diesem Repo)
- Vorgehen: `docs/ai/questions_archive.md`, `questions.md` und `ledger.md` in `D:\dev\rufeger\bandliste` durchgehen und je Punkt entscheiden — Template-Regel, Baustein unter `docs/project/coding_rules.d/`, neuer Agent oder Skill, oder nichts
- was ins Template gehört, bekommt hier eine eigene Nummer; umgesetzt wird im Template, nicht in der Notiz
- Umfang unbekannt: erst nach dem Durchgang lässt sich sagen, ob das eine Sitzung wird oder mehrere; bei mehr als etwa zehn Kandidaten in Teilaufgaben je Themenbereich schneiden

<a id="b23"></a>
### B23 · Design-Wege über /design hinaus

- erledigt 2026-09-14, teils überholt durch B24
- recherchiert und in `CLAUDE.md` § 5 als Tabelle aufgenommen: Screenshot direkt einfügen (Grenzen 8000×8000 px, 10 MB, unter 200 px unzuverlässig), Webseite über Chrome-Screenshot statt `WebFetch` (liefert nur HTML als Text), Figma über den offiziellen MCP-Server (remote per Plugin oder Desktop über `127.0.0.1:3845/mcp`, als Beispiel in `.mcp.json.example`), `.psd` nur über PNG-Export
- Kernaussage jetzt: der **Rückkanal** — laufende Anwendung in Claude in Chrome öffnen und das Gebaute gegen die Vorlage prüfen (Anthropic nennt genau diesen Ablauf als Beispiel)
- Faustregel für ein bestehendes Projekt mit Komponentenbibliothek: Screenshot → echter Code → Prüfung im Browser, ohne Zwischenformat

<a id="b24"></a>
### B24 · Design-Schalter raus, MCP-Katalog und drei Design-Skills rein

- erledigt 2026-09-14
- Schalter `Design` für Claude Design zurückgebaut — ein Schalter für ein einzelnes Cloud-Werkzeug war der falsche Zuschnitt
- stattdessen: `.claude/mcp-katalog.md` mit 21 geprüften MCP-Servern (Kennung, Anbieter, Transport, Secrets, Reifegrad, Einbindungsbefehl), auswählbar über `AI-CONFIG.md` § `MCP-Server`
- dazu die Skills `/design-ideas` (drei bis vier Varianten als Playwright-Screenshots zur Auswahl), `/design-build` (umsetzen im echten Code, Selbstprüfung im Browser, höchstens drei Runden), `/design-assets` (Logo, Icons, Favicons als SVG; Rasterbilder nur über ein Bildmodell per MCP)
- zwei Befunde aus der Recherche, die den Zuschnitt bestimmt haben: Claude erzeugt keine Rasterbilder — SVG ist Code, Fotorealistisches braucht einen externen Dienst mit Kosten je Bild; rein KI-generierte Werke sind nicht automatisch urheberrechtlich geschützt (menschlicher Schöpfungsanteil nötig) — bei einem Logo wichtiger als die Bildqualität, steht deshalb im Skill

<a id="b25"></a>
### B25 · MCP-Auswahl aus AI-CONFIG.md automatisch einrichten

- angelegt 2026-09-14, Priorität mittel
- der Schlüssel `MCP-Server` hält heute nur fest, welche Server zum Projekt gehören — eingerichtet werden sie von Hand
- Zu bauen: `sync-config.py` liest die Kennungen, gleicht sie gegen `.claude/mcp-katalog.md` ab und schreibt die Einträge nach `.mcp.json` (Secrets nur als `${VAR}`, nie Werte)
- Aufnehmen läuft automatisch durch, Entfernen braucht eine Zusage — in `.mcp.json` kann inzwischen projekteigene Konfiguration stehen
- dazu: unbekannte Kennungen melden statt still übergehen, benötigte Umgebungsvariablen in `.env.example` ergänzen, damit sichtbar ist, was fehlt
- Voraussetzung: maschinenlesbarer Katalog — die Markdown-Tabelle taugt dafür nur bedingt, ein `.claude/mcp-katalog.json` neben der Doku wäre der sauberere Weg

<a id="b26"></a>
### B26 · README des Zielprojekts blieb der Vorlagentext

- erledigt 2026-09-14
- Befund in `bandliste`: nach dem Nachrüsten stand weiterhin der englische „Nuxt Minimal Starter"-Text; die Regel verlangte nur, einen Abschnitt „Zusammenarbeit mit KI-Assistenten" zu **ergänzen** — genau das war geschehen (Einleitung oben, Starter-Text darunter, doppelte Installationsanweisungen für vier Paketmanager)
- Skill und Checkliste verlangen jetzt, die README zu **prüfen und zu überarbeiten**, wenn sie erkennbar nie angefasst wurde, mit Vorgabe für den Aufbau (Schnellstart, Befehlstabelle, Struktur, Doku-Wegweiser) und der Auflage, ehrlich zu bleiben — was rot ist oder fehlt, gehört sichtbar in die Tabelle
- Nachtrag am selben Tag: erster Versuch war trotzdem falsch — README begann mit dem technischen Schnellstart, die Arbeitsweise stand weit unten; bei einem KI-entwickelten Projekt gehört das nach oben, direkt nach der Einleitung, für Menschen lesbar mit `AI-CONFIG.md` an erster Stelle
- Lehre (zweimal dieselbe): „ergänzen" und „erwähnen" sind schwache Anweisungen — wo Position und Lesart zählen, muss die Regel beides vorgeben, sonst landet der wichtigste Teil unten und liest sich wie eine Dateiliste

<a id="b27"></a>
### B27 · Mehrsprachigkeit des Templates konzipieren (früher: Sprache aus AI-CONFIG.md wirkt nicht)

- angelegt 2026-09-14, Priorität hoch
- Schlüssel `Sprache` steht in der Konfiguration, hat aber keine Wirkung — das Template ist durchgehend deutsch, ein angelegtes Projekt bleibt es auch
- (a) Template auf Englisch umstellen: für GitHub ist Deutsch die falsche Ausgangssprache — betrifft `AGENTS.md`, `CLAUDE.md`, `README.md`, alle Checklisten, Skills, Agenten-Rollen, Regelbausteine, Doku-Skelette und Script-Ausgaben; größter Einzelposten dieser Liste
- (b) Sprache beim Anlegen/Nachrüsten anwenden: steht in `AI-CONFIG.md` § `Sprache` etwas anderes als die Ausgangssprache, wird das Zielprojekt darin geführt — Doku, Kommentare, Commit-Messages **und** die Kommunikation des Assistenten; keine reine Textersetzung, Vorlagen müssten zweisprachig vorliegen oder beim Anlegen übersetzt werden
- zu klären vor Beginn: zweisprachige Pflege (doppelter Aufwand, verlässlich) oder einmalige Übersetzung beim Anlegen (billiger, aber `/update-template` bekommt danach in jeder Zeile Konflikte) — diese Entscheidung bestimmt den ganzen Rest
- **Entschieden 2026-09-17 (Wolfgang):** Schlüssel `Sprache` vorerst aus `AI-CONFIG.md` entfernt, Deutsch ist Standard; Priorität mittel, erst Konzept
- Ideensammlung für das Konzept (Optionen, noch nicht bewertet):
  - **Branch je Sprache** (`main` deutsch, `en` englisch): Update-Weg bleibt Merge, aber jede Template-Änderung muss in alle Branches übertragen werden; Drift-Gefahr
  - **Verzeichnisse je Sprache** (`i18n/de/…`, `i18n/en/…`), `create-project` kopiert die gewählte Fassung an die Standardorte: klare Trennung, doppelte Pflege, `update-template` muss die Zuordnung kennen
  - **Platzhalter + Übersetzungsdateien** (Texte als Schlüssel, `de.json`/`en.json`, beim Anlegen gerendert): eine Quelle für die Struktur, aber Markdown-Regeltexte in Schlüssel zu zerlegen macht sie schwer lesbar und editierbar
  - **Nur per KI übersetzen** beim Anlegen/Update: keine Pflege zweier Fassungen, aber nicht reproduzierbar, kostet Token, jede Template-Änderung erzeugt Konflikte in übersetzten Dateien
  - **Mischform:** Scripte und Script-Ausgaben per Übersetzungsdatei (klein, mechanisch), Regel-/Doku-Texte als Verzeichnis je Sprache oder per KI
  - **Nur Englisch als Ausgangssprache**, Deutsch als Übersetzung — betrifft auch die GitHub-Sichtbarkeit (siehe a)
  - **Englisch als Basis, Projektsprache nur für neue Inhalte** (Idee Wolfgang 2026-09-17): Template, Regeln, Skills und Scripte bleiben durchgehend englisch; beim Projektstart fragt der Assistent nach der Projektsprache oder liest sie aus `AI-CONFIG.md` (z. B. `Language: de`). Ab dann entsteht alles, was neu in `docs/` geschrieben wird (Konzepte, Aufgaben, Fragen, Journal, Projekt-Doku), in dieser Sprache; die vom Template gelieferten Dateien bleiben englisch. Vorteil: keine Übersetzung der Vorlage, keine Update-Konflikte. Zu klären: gemischtsprachige Dateien (Formulare aus dem Template mit Einträgen in Projektsprache), Überschriften/Schlüsselwörter, die Scripte parsen (`* Antwort:`, `Offen:`), Kommunikation im Chat
- Ergänzung Wolfgang 2026-09-17 zu gemischten Dateien und festen Schlüsselwörtern: Originaltexte und
  Schlüsselwörter je Sprache an einer Stelle im Repo ablegen, z. B. als Zuordnung
  `{ filename: 'docs/ai/questions.md', question_marker: { en: '* Question:', de: '* Frage:' }, changed: false }`
  — Scripte lesen die Marker daraus statt fest verdrahtet, `changed` zeigt, ob eine Datei vom Original abweicht
  (Grundlage für Updates). Wahrscheinlich versioniert.
- Chat-Sprache: wie festgelegt, sonst wie der Nutzer schreibt. Annahme Wolfgang: für das Modell ist es kein
  Problem, auf eine deutsche oder spanische Anweisung hin englische Texte zu lesen und zu schreiben — die
  Regeldateien können also englisch bleiben, auch wenn im Chat und in `docs/` eine andere Sprache gilt.
- Kriterien fürs Konzept: Aufwand je Template-Änderung, Konfliktverhalten bei `/act-update-template`, Reproduzierbarkeit, Lesbarkeit der Quelltexte, Übersetzung der Kommunikation des Assistenten (reine Anweisung genügt vermutlich)

<a id="b28"></a>
### B28 · no_replace steht in AGENTS.md anders als in template.json

- angelegt 2026-09-14, Priorität niedrig
- `AGENTS.md` § „Template-Herkunft und Updates" nennt `docs/ai/checklists.md` und `.claude/skills/create-project/SKILL.md` als nie platzhalter-ersetzt
- `.claude/template.json` führt unter `no_replace` aber nur die drei `.py`-Dateien; `EXCLUDED_FROM_REPLACE` in `setup-lib.py` deckt sich mit der JSON-Fassung
- dritte Fundstelle: `docs/ai/checklists.md` § „Neues Projekt", Schritt 3, behauptet dasselbe wie `AGENTS.md`
- zwei Dokumente sagen das eine, der Code das andere — gefunden beim Einbau der Statuszeilen-Ersetzung
- erst prüfen, welche Fassung gewollt ist (zeigen beide Dateien Platzhalter absichtlich als Beispiel?), dann die andere angleichen — nicht blind eine Liste erweitern

<a id="b29"></a>
### B29 · Rückmeldung abgeleiteter Projekte

- angelegt 2026-09-14, Priorität offen, Status: in Arbeit
- Projekte aus dem Template sollen sich freiwillig als Testkandidat melden (Datum, öffentliche Repo-URL, Weg neu/nachgerüstet, Ausfüllart leer/Interview/Config), damit `.templatedev` ihre Weiterentwicklung auswerten kann
- Konzept mit vier Optionen und Aufwand: `../project/concepts/feedback.md`; erst `Q1`–`Q3` entscheiden, dann bauen — es geht um fremde Daten, Gegenstelle gab es anfangs nicht
- Stand 2026-09-14: `Q1`–`Q3` beantwortet (eigener Endpunkt, Frage einmalig bei `/finalize`; Steuerung inzwischen doch in `AI-CONFIG.md`, siehe Nachtrag im Konzept); Client-Seite gebaut (`.claude/scripts/feedback.py`), Schnittstellenvertrag im Konzept
- Stand 2026-09-15 (seit T5 unter neuem Namen): beide Gegenstellen gebaut — `.templatedev/scripts/feedback-endpoint.php` (öffentliches `POST`, JWT-geschütztes `GET /inbox` + `POST /ack`) und `.templatedev/scripts/feedback-fetch.py`; belegt gegen einen laufenden `php -S`; Sendeprotokoll im Projekt gitignorierbar (`feedback.py --enable --protokoll lokal`), Abgeholtes hier grundsätzlich gitignored
- Offen: Ausrollen auf `rufeger.de` (Datei, Geheimnis, Ablage außerhalb des Web-Roots), Datenschutzhinweis unter der URL, danach die eigentliche Auswertung

<a id="b30"></a>
### B30 · Löschen trifft nie ungesicherte Dateien

- angelegt und entschieden 2026-09-15, erledigt 2026-09-15, Beleg im Ledger
- `remove_maintenance_files`, `remove_optimizer_files` und `remove_tool_files` (`setup-lib.py`) löschten Pfade, ohne zu prüfen, ob sie überhaupt anderswo liegen
- `.claude/maintenance/reports/` ist gitignored — beim Abschalten der Wartung wären Berichte unwiederbringlich weg
- Umsetzung: gemeinsamer Helfer, der vor dem Löschen `git status --porcelain --ignored -z -- <pfad>` fragt; gitignorierte, ungetrackte und lokal geänderte Pfade bleiben liegen und werden zurückgemeldet (Muster: `rename-lib.py` B10, `git check-ignore`)
- kein Git-Repo = nicht prüfbar = liegen lassen und melden
- verworfene Alternative (`.bak`/`.disabled` statt Löschen): veraltet gegenüber dem Template, verschmutzt Diffs, spart die CLAUDE.md-Arbeit nicht

<a id="b31"></a>
### B31 · Abgewählte Pfade bleiben beim Template-Update draußen

- angelegt und erledigt 2026-09-15, Beleg im Ledger
- wer `Wartung: aus`, `Code-Optimierung: aus` oder ein KI-Werkzeug abwählt, bekam die Dateien beim nächsten `update-template.py --apply` teilweise zurück
- belegt an `update-template.py:1025-1070`: (a) ändert das Template eine gelöschte Datei, entsteht ein `DU`-Konflikt, der nur für `keep_local`-Pfade automatisch „gelöscht belassen" wird — `optimizer.md` und `.claude/maintenance/**` standen dort nicht, also kam bei jedem Update eine Rückfrage; (b) legt das Template eine **neue** Datei in dem Bereich an, wurde sie konfliktfrei hinzugefügt, ohne dass jemand gefragt wurde
- Umsetzung: `update-template.py` leitet die abgewählten Pfade zur Merge-Zeit aus `.claude/template.json` § `applied_config` ab (`Wartung`, `Code-Optimierung`, `KI-Werkzeuge` gegen `MAINTENANCE_REMOVE_PATHS`/`OPTIMIZER_REMOVE_PATHS`/Werkzeugpfade in `setup-lib.py`) und behandelt sie für diesen Lauf wie `template_only`: `DU` ohne Rückfrage gelöscht belassen, neu hinzugekommene Dateien darunter nach dem Merge entfernen (`_remove_template_only()` als Muster)
- keine neue Liste in `template.json` — sie würde gegenüber `AI-CONFIG.md` veralten; schaltet jemand auf `ein`, fällt der Ausschluss von selbst weg

<a id="b32"></a>
### B32 · Feedback muss nochmal neu bearbeitet werden

- umgesetzt 2026-09-15 bis auf die Endpunkt-Inbetriebnahme (Beleg im Ledger); offen bleiben das Ausrollen auf `rufeger.de` samt Datenschutzhinweis und die Frage, ob `Feedback` beim Abschluss der Einrichtung aktiv angeboten statt nur erwähnt wird
- Entschieden am 2026-09-15 (Wolfgang), drei Punkte, die den Bau bestimmen:
  - Umfang `d` entfällt: echte Dateien aus `docs/ai`/`docs/project` widersprechen der Zusage in `AGENTS.md` („nie Dateien, nie Projektbezug") und dem Filter in `feedback.py`; `b` meldet Strukturänderungen weiterhin, aber als **Beschreibung**, nicht als Datei
  - Statistiken (`a`) kommen aus `git log` und dem Dateisystem, `ai.log` nur wenn vorhanden; nicht Ermittelbares wird weggelassen statt geschätzt
  - der adaptive Takt bekommt einen eigenen `SessionStart`-Hook, unabhängig von der Wartung (die ist abwählbar)
- Schnitt in Aufgaben (in dieser Reihenfolge, je mit eigenem Beleg):
  1. `AI-CONFIG.md`: neuer Schlüssel `Feedback-Umfang` (Mehrfachauswahl `a,b,c`, Default `a,b,c`), `Feedback-Takt` um `adaptiv` erweitert; `sync-config.py` setzt beides um
  2. Erhebung je Umfang in `feedback.py` (git log, Dateisystem, `ai.log` falls vorhanden)
  3. Ablage umgebaut: `<subject>.md` + `<subject>.json` unter `docs/ai/template-feedback/`, beim Senden nach `sent/`; bisheriger Ausgang `.claude/feedback-outbox.json` entfällt
  4. `feedback.md` als Fragebogen (Fragen, Freitext; beim Senden Antworten zusammenfassen, ans Dateiende anfügen, Fragen/Überschriften wiederherstellen)
  5. eigener `SessionStart`-Hook für die Erinnerung beim Takt `adaptiv`
  6. Endpunkt auf Schema 2 (`.templatedev/scripts/feedback-endpoint.php`): neue Felder, Wortlisten, 32-KB-Deckel prüfen
  7. Zusagetexte nachgezogen: `AGENTS.md`, `/finalize`, `/feedback`, `docs/ai/template-feedback/README.md`

**Ursprünglicher Wunsch (Wortlaut):**

```text
Frage nach Erstellung oder Anbindung einer App nach Feedback: ja (empfohlen) oder nein
bei ja:
  - Umfang: nur einmalige Registrierung(Art,Datum,KI-Tools,Stack) und manuelles Feedback direkt als Antwort, alles (ohne (d) also ohne echte Projektdaten, empfohlen), wirklich alles oder
   (mehrere auswählbar)
   a) statistische Daten (Art der Erstellung, Datum, Häufigkeit der Nutzung, Anteil KI-generierter Code, Häufigkeit von Änderungen an docs/ai, Anzahl
   Dateien im Repo, Größe des Repo, öffentliche Repo URL des Projekts ?, ...)
   b) Änderungen an Dateien und Daten die KI betreffend (AGENTS.md, CLAUDE.md, .claude/agents, .claude/skills, ...) oder wenn Änderungen an der Struktur von Dateien in docs besprochen werden (xy als Tabelle, Abschnitt xy mit mehreren Zeilen und Einrückung darstellen, backlog um Spalte xy erweitern, ... was auch immer eine Optimierung und kein "Inhalt" ist, also OHNE echte Dateien aus docs/ai)
   c) Tool-Nutzung (MCP server zugefügt, skill aktualisiert oder erstellt, agent definiert oder geändert, neues script oder aktualisiert, ...)
   d) Änderung auch an docs/ai und docs/project (hier zwar nur wirklich relevante Änderungen, aber auch echte Dateien mit Inhalt)
  - Häufigkeit: autom. (empfohlen, wöchentlich macht keinen Sinn bei Entwicklern, die nur 1x die Woche coden, also autom. an das Nutzerverhalten angepasst, User wird je nach Feedback-Anzahl, Dringlichkeit (z.B. krit. Fixes), Datum des letzten Sendes, Häufigkeit der Arbeit am Projekt, ... autom. an Feedback erinnert oder der Prozess autom. angestossen), max. tägl., max. wöchentlich, manuell mit "/send-feedback" oder "schicke Feedback"
  - Bestätigung: Diskrete Nachfrage im Chat, ob das gesammelte Feedback in docs/ai/template-feedback gesendet werden darf (empfohlen), autom. im Hintergrund
  - Ordner template-feedback in .gitignore zufügen? nein (empfohlen), ja

docs/ai/template-feedback/
   - hier wird von der lokalen AI des Projektes gesammeltes Feedback in Dateien hinterlegt. Gesammelt werden soll nur der freigegebene Umfang und auch nur dann,
     wenn die Daten sinnvolle Ergänzungen im Template Project darstellen könnten (Optimierungen, v.a. am Arbeitsablauf, Kommunikation KI/Mensch, Texten im Template Project, Scripten, ...)
     Gespeichert wird eine [name|title|subject].md mit einer textuellen Zusammenfassung, sowie eine [name|title|subject].json mit den Daten, die besser im Template Projekt verarbeitet werden können.
     Beim Senden Dateien in den Unterordner sent/ verschieben.
   - feedback.md (hier kann der Entwickler selbst Feedback senden. Ein paar vorgefertigte Fragen beantworten, Feedback in Textform, Vorschläge und Ideen, Programmiererfahrung, Erfahrung mit KI, ...).
     Beim Senden beantwortete Fragen und Textantworten zusammenfassen und ans Ende der Datei anfügen, dann Fragen und Abschnitts-Überschriften wiederherstellen für ein weiteres oder späteres Feedback

Werden alle Fragen mit ok bestätigt, also die Empfehlungen angenommen, so wird Feedback wahrscheinlich wöchentlich nach kurzer Rückfrage gesendet und dabei auf den Ordner docs/ai/template-feedback/ verwiesen, um ggf. feedback.md manuell zu ergänzen.
Das solle datenschutkonform sein und nicht zu aufdringlich. Frequenz und Umfang soll der User ja jederzeit über die AI-CONFIG umstellen können.
```

<a id="b33"></a>
### B33 · Aufgaben für den Auftraggeber erst eintragen, wenn sie ausführbar sind

- angelegt 2026-09-16
- Wolfgang liest „Aufgaben nur für {{AUFTRAGGEBER}}" als Arbeitsliste und führt die Schritte nacheinander aus — eine `Offen:`-Zeile hält ihn davon nicht ab
- Anlass: die Test-Aufgabe für `bandliste` stand in `.templatedev/docs/ai/tasks.md` (damals `.templatedev/tasks.md`), bevor T1–T3 gebaut und gepusht waren
- Regel für `AGENTS.md` § Tabu-Bereich und `docs/ai/README.md`: eine Aufgabe für den Auftraggeber erscheint erst, wenn alle Voraussetzungen erfüllt sind (Code gepusht, Fragen beantwortet); bis dahin steht sie als Folgeschritt in der Aufgabe des Assistenten, die sie auslöst

<a id="b34"></a>
### B34 · Issue-Tracker ohne Git anbinden — Jira, YouTrack, Linear

- angelegt 2026-09-16, Priorität später
- `/issue` und `/integrations` (T1, T3) bauen zunächst nur GitLab und GitHub (Q11)
- danach dieselben Abläufe über MCP (`atlassian`, `linear`); YouTrack fehlt noch im Katalog `.claude/mcp-katalog.md`

<a id="b36"></a>
### B36 · Template-Update bleibt als halber Merge stehen

- angelegt 2026-09-17, aus einer Rückmeldung
- `update-template.py --apply` ohne `--commit` hinterlässt einen gestagten Merge mit `MERGE_HEAD`
- `--continue` setzt `base_commit` und die Historie danach auf den inzwischen neu gefetchten Template-Stand, ohne dessen Commits gemergt zu haben
- Zu bauen: Skill schließt mit Commit ab oder fragt ausdrücklich; `--status` und SessionStart-Hook warnen bei offenem Merge; `--continue` nimmt den Stand aus `MERGE_HEAD`, nicht aus dem letzten Fetch

<a id="b37"></a>
### B37 · Neue Schlüssel in AI-CONFIG.md gehen beim Update verloren

- angelegt 2026-09-17, aus einer Rückmeldung
- `AI-CONFIG.md` steht in `keep_local`; bei ausgefüllten Tabellen kollidiert fast jede Template-Änderung, die Projektfassung gewinnt ganz, neue Zeilen verschwinden still
- `sync-config.py` meldet fehlende Schlüssel nicht
- Zu bauen: Schlüssel beider Seiten vergleichen, fehlende Zeilen mit Standardwert ergänzen und melden; `sync-config.py --check` meldet Schlüssel, die das Template kennt

<a id="b38"></a>
### B38 · Update bringt nach /finalize entfernte Abschnitte zurück

- angelegt 2026-09-17, aus einer Rückmeldung
- betrifft abgeschlossene Projekte (`setup_complete`)
- ein Konflikt auf Template-Seite liefert Checklisten-Abschnitte zum Anlegen/Nachrüsten, `template-only`-Blöcke und Zeilen zu entfernten Scripten wieder mit; das Script entscheidet aktuell nicht selbst
- Zu bauen: bei `setup_complete` diese Abschnitte/Blöcke beim Update automatisch verwerfen (dieselben Marker, die `/finalize` entfernt)

<a id="b39"></a>
### B39 · Feedback-Ablage nach dem Versand widersprüchlich

- angelegt 2026-09-17, aus einer Rückmeldung
- nach dem Senden liegen Einträge in `sent/`, tragen aber noch „wartet auf Versand"
- die Sendeprotokolle (`.json`) liegen ohne `.md` im Hauptordner und sehen wie hängengebliebene Einträge aus
- bei `Feedback: automatisch` und Takt `sofort` löst `--add` keinen Versand aus
- Zu bauen: Status beim Verschieben auf „gesendet <Zeit>", Protokolle nach `sent/protokolle/`, bei automatisch+sofort direkt senden
- Ergänzt 2026-09-17 (zweite Rückmeldung): Abschnitt „Bereits gesendet" in `feedback.md` sammelt nur selbst geschriebene Antworten und wirkt trotz Sendungen leer — umbenennen in „Von dir bereits gesendet", README erklärt Eintrag (Lesefassung) vs. Protokoll (Nutzlast mit Metadaten)
- Option: ein Eintrag = eine `.md` mit Front-Matter für Maschinenfelder (Art, Titel, Datum, Status, gesendet) statt `.md` plus `.json`; Status wird beim Versand dort gesetzt, Protokoll bleibt eigene Datei

- Bestätigt 2026-09-17 (dritte Rückmeldung, vom Code gedeckt): `_protokollieren` schreibt nach `LOG_DIR_REL` statt `sent/protokolle/` — betrifft `--send` und `--direkt` gleichermaßen; `--status` und README mitziehen
- **Erledigt 2026-09-17:** Einträge als eine `.md` mit YAML-Front-Matter (`art`, `titel`, `datum`, `status`, `gesendet`); Lesen akzeptiert zusätzlich das alte Paar `.md`+`.json`; beim Versand werden `status: gesendet` und die Zeit gesetzt (`feedback.py`). Offen bleiben Ablage der Sendeprotokolle, Umbenennung des Abschnitts „Bereits gesendet“ samt README-Erklärung und Sofortversand bei automatisch+sofort.
- Nachtrag 2026-09-17 (Wolfgang): Ordner heißt `sent/protocols/` (Dateinamen englisch), nicht `sent/protokolle/`; noch nicht veröffentlicht, deshalb ohne Migration.

<a id="b40"></a>
### B40 · Formatregel für Fragen rendert als ein Absatz

- angelegt 2026-09-17, aus einer Rückmeldung
- das Beispiel in `docs/ai/README.md` § Fragen nutzt eingerückte Zeilen ohne Leerzeilen; in IDE-Vorschau und auf GitHub fließen Frage, Optionen und Antwort zusammen
- bewährt: Frage fett als eigener Absatz, Optionen als Liste `- a) …`, Leerzeile vor Liste und Antwortzeile
- passt zu T5 (Formregeln in `.templatedev/`): Regel und Beispiel im Template zuerst ändern, dann erben
- umgesetzt in `.templatedev/docs/ai/questions.md` (T5 Schritt 2, 2026-09-17)

<a id="b41"></a>
### B41 · Erläuterungen aus AI-CONFIG.md auslagern

- angelegt 2026-09-17, aus einer Rückmeldung
- die langen Absätze zwischen den Tabellen (Modell, Feedback, MCP-Server …) vermischen Steuerung und Doku und verursachen Update-Konflikte
- Vorschlag: Hilfedatei unter `docs/ai/`, in `AI-CONFIG.md` bleibt die Spalte „Bedeutung" und ein Verweis
- hängt mit B37 zusammen

<a id="b42"></a>
### B42 · create-project.py --check warnt vor bewusst gehaltenen Altnamen

- angelegt 2026-09-17, Priorität niedrig
- nach dem Präfix `act-` stehen alte Skill-Pfade absichtlich in den Entfernen-Listen, damit bestehende Projekte sie beim Update loswerden (`.claude/skills/run-maintenance` in `MAINTENANCE_REMOVE_PATHS`)
- `check_stale_remove_paths` meldet sie als „möglicherweise veraltet"
- Zu bauen: Altnamen kennzeichnen (eigene Liste oder Kommentar-Marker) und in der Prüfung auslassen

<a id="b43"></a>
### B43 · `sync-config.py --apply` bricht nach dem Übernehmen der Werte ab

- angelegt 2026-09-17, aus einer Rückmeldung, Priorität hoch
- `files-lib.py` nutzt `time.strftime` beim Setzen von `applied_config_stand` (Zeile 643), importiert `time` aber nicht → `NameError`
- Folge: der zuletzt umgesetzte Stand wird nie gespeichert, der SessionStart-Hook meldet dieselben Änderungen immer wieder
- Zu bauen: Import ergänzen; Smoketest, der `--apply` einmal bis zum Ende durchlaufen lässt, damit ein fehlender Import auffällt

- **Erledigt 2026-09-17** (B36–B43): siehe Tabellen; Review in vier Runden, Befunde im Journal.

<a id="b44"></a>
### B44 · Python als Voraussetzung, Hooks ohne Python

- angelegt und erledigt 2026-09-17, Wunsch Wolfgang
- README und `.github/README.md` § Voraussetzungen: Python 3.9+ (Minimum aus `files-lib.py`), was ohne geht, Installation je Plattform
- erster SessionStart-Hook prüft ohne Python, ob ein Interpreter wirklich läuft, sonst eine Warnzeile
- alle Python-Hooks wählen den ersten Kandidaten aus `python3`, `python` per Probe (Windows-Store-Platzhalter)

<a id="b45"></a>
### B45 · Pfade außerhalb des Projekts plattformgerecht

- angelegt und erledigt 2026-09-17, Wunsch Wolfgang
- Regel: im Gespräch nur den Pfad der aktuellen Plattform, in Doku `~` mit Erklärung oder Liste je Plattform, Scripte zur Laufzeit
- `AGENTS.md` § Doku, Tests, Coding; `CLAUDE.md` § 4 (`~/.claude.json`); `.templatedev/docs/project/coding_rules.md`

<a id="b46"></a>
### B46 · Hooks: Interpreter-Probe je Aufruf kostet Zeit

- angelegt 2026-09-17 aus dem Review zu B44, Priorität niedrig
- jeder Hook startet Python zweimal (Probe + Script), auch Logging-Hooks bei `AI_LOG=aus`
- Zu bauen, falls spürbar: gewählten Interpreter je Sitzung in einer gitignorierten Datei merken

<a id="b47"></a>
### B47 · Hooks führen ungeprüfte Merge-Fassung aus

- angelegt 2026-09-17 aus dem Sicherheitsreview, Priorität niedrig
- Hooks starten die Scripte im Arbeitsbaum, während eines Merges also die gemergte, noch nicht committete Fassung
- `update-template.py --check` fängt einen erkannten Template-Merge ab; offen bleibt ein `MERGE_HEAD`, den `_merge_is_from_template` nicht erkennt
- Zu bauen: Hooks bei jedem offenen `MERGE_HEAD` nur melden statt Scripte laufen zu lassen, oder bewusst hinnehmen

<a id="b48"></a>
### B48 · `/act` zeigt nur die Befehle, die gerade passen

- angelegt 2026-09-17, Idee Wolfgang
- frischer Klon (Marker `is_template`, noch nicht angelegt): nur `act-create-project` und `act-apply-template` (plus `/act` selbst)
- laufendes Projekt (`setup_complete` oder nach `/act-finalize`): diese beiden nicht; während der Einrichtung zusätzlich `act-finalize`
- im Template-Checkout selbst zusätzlich die Pflege-Befehle (`act-process-feedback`)
- Zu bauen: `act-help.py` liest `.claude/template.json` und filtert; Skill-Frontmatter könnte ein Feld wie `phase: setup|projekt|pflege` tragen statt einer Namensliste
- Entschieden 2026-09-17 (Wolfgang): `/act all` zeigt zusätzlich die ausgeblendeten Befehle (Parameter englisch)

<a id="b49"></a>
### B49 · Skill `act-check-translations`

- angelegt 2026-09-17, Idee Wolfgang, Priorität offen (Vorschlag mittel)
- Schritt 1 Erkennen, je Stack: z. B. Nuxt `@nuxtjs/i18n` + `locales/*.json`, Vue/React i18n-Bibliotheken, gettext `.po`, Rails/Laravel `lang/`; nichts gefunden → melden und beenden
- Schritt 2 Vollständigkeit per Script: Schlüssel je Sprache gegen die Default-Sprache (fehlend, überzählig, leer, identisch mit Default = vermutlich unübersetzt), Platzhalter-Parität (`{name}`), im Code verwendete Schlüssel ohne Eintrag
- Schritt 3 `extended`: Seiten je Sprache per Playwright öffnen, sichtbare Texte auf Default-Sprache, rohe Schlüssel (`home.title`) und Platzhalter prüfen
- Schritt 4 Texte aus Backend/Datenbank: ist ein Datenbankzugriff vorhanden (MySQL-/DB-MCP-Server, Zugangsdaten in `.env`, lokale DB als Docker-Container), werden auch dort Übersetzungen geprüft — Tabellen mit Sprachspalten oder Übersetzungstabellen auf fehlende/leere Einträge je Sprache; **nur lesend** (`AGENTS.md` § Zugriff auf laufende Systeme), Zugangsdaten nie auf die Kommandozeile; ohne Zugriff nur melden
  (Ergänzung Wolfgang 2026-09-17)
- Ergebnis nach Schwere, Befüllen fehlender Übersetzungen nur nach Freigabe
- vorher Konzept nach Checkliste „Idee aufnehmen"; Script unter `.claude/scripts/` (Stdlib), Stack-Erkennung erweiterbar

<a id="b50"></a>
### B50 · Skill `act-seo`

- angelegt 2026-09-17, Idee Wolfgang, Priorität offen (Vorschlag mittel)
- Code/Build: gültiges HTML, `<html lang>`, `<title>`/`meta description` je Seite, Canonical, `hreflang` bei Mehrsprachigkeit, Open Graph, eine `h1` und saubere Überschriftenfolge, Textmenge, Alt-Texte
- Auslieferung: Inhalte per SSR/SSG im ausgelieferten HTML (nicht erst per JS), `robots.txt`, `sitemap.xml`, interne Verlinkung, verwaiste Seiten, doppelte Titel/Inhalte, Statuscodes
- live, nur wenn das Projekt veröffentlicht ist: Suchergebnis-Darstellung (Titel, Beschreibung), Indexierung; Daten über die Google Search Console per API/MCP (Zugang nötig → Tabu-Bereich bzw. Freigabe)
- Pagerank ist öffentlich nicht mehr abrufbar — stattdessen Search-Console-Kennzahlen (Impressionen, Klicks, Position)
- neuer Schlüssel in `AI-CONFIG.md`, z. B. `Live-Adresse` (URL, leer = nicht live) oder `Veröffentlicht: ja/nein` samt Datum; hängt an B37 (Schlüssel werden jetzt nachgezogen)
- vorher Konzept; ggf. Lighthouse-SEO-Audit per Playwright/CLI als Basis statt Eigenbau

<a id="b51"></a>
### B51 · Frischer Klon erklärt sich selbst

- angelegt 2026-09-17, Wunsch Wolfgang, Priorität mittel
- frisch geklontes Template (`is_template`, kein lokaler Marker `.templatedev/.maintainer`): jede Eingabe, die nicht erkennbar anlegen oder nachrüsten will — auch „hallo" oder „wie geht das hier" —, bekommt zuerst einen kurzen Hinweis auf Weg 1 (`/act-create-project`) und Weg 2 (`/act-apply-template`), unabhängig vom Modell
- entschieden: Marker-Datei für den Pflege-Checkout (gitignored); gilt, solange das Repo Vorlage ist
- erster Entwurf blockte per Script mit festem Text und Regex-Durchlass — verworfen: blockte die Antworten im Anlege-Interview und bewertete Freitext schlecht
- entschieden 2026-09-17 (Wolfgang): lieber ein paar Token — `UserPromptSubmit`-Hook `template-welcome.py` gibt dem Modell per `additionalContext` die Anweisung, die Eingabe zu bewerten; Werkzeuge ohne Hooks über die Regel in `AGENTS.md` (Block „Noch nicht initialisiert")
- beim Anlegen/Nachrüsten werden Script, Hook-Eintrag und `.gitignore`-Zeile entfernt
- **Erledigt 2026-09-17**, Review ALLOW. Restpunkte: ein vorher angelegtes Projekt bekommt den Hook-Eintrag per `/act-update-template` zurück (Script fehlt, `is_template` fehlt → still, kostet einen Python-Start; wie beim Wartungs-Hook); `/ACT` in Großbuchstaben fängt `act-help.py` nicht ab

<a id="b52"></a>
### B52 · Restrisiken des Pflege-Projekts belegen

- angelegt 2026-09-17 aus dem Review zu T5, Priorität niedrig
- `claudeMdExcludes` mit Windows-Laufwerksbuchstaben per Versuch belegt (D:/…); auf macOS/Linux einmal gegenprüfen
- `act-help.py` sucht Skills bis zum Git-Root; ob Claude Code selbst genau dort stoppt (Monorepo), ist nicht belegt
- `.templatedev/` hat keine eigenen Sub-Agenten — dass sie aus dem Root kommen, zeigte der Versuch vom 2026-09-16; in der ersten echten Pflege-Sitzung bestätigen
- `update-template.py --apply` im Pflege-Ordner zeigt den Diff und schreibt ohne Rückfrage — die Rückfrage stellt der Skill; ggf. `--yes` verlangen
