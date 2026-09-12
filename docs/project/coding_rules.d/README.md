# Coding-Regeln — Bausteine je Sprache/Framework

Ein Baustein je Sprache oder Framework (`php.md`, `vue.md`, `tailwind.md`, …), ergänzend zu den generischen
Regeln in `docs/project/coding_rules.md`. Ein Projekt behält nur die passenden Bausteine, kann aber jederzeit
weitere aus dem Template nachladen (z. B. Start mit PHP, später kommen Vue und Tailwind dazu).

Verwaltet werden die Bausteine ausschließlich über `.claude/scripts/guidelines.py` — **nicht von Hand**
eintragen oder löschen, sonst gerät der Indexblock in `coding_rules.md` außer Tritt:

```text
python .claude/scripts/guidelines.py --list                 # aktive + zusätzlich verfügbare Bausteine
python .claude/scripts/guidelines.py --available             # nur verfügbare Kennungen (für Skripte)
python .claude/scripts/guidelines.py --add <kennung>[,...]    # Baustein(e) aus dem Template holen
python .claude/scripts/guidelines.py --remove <kennung>[,...] # Baustein(e) entfernen
python .claude/scripts/guidelines.py --sync                   # Indexblock nach manuellem Kopieren neu schreiben
```

Regeln je Baustein:

- Dateiname = Kennung in Kleinbuchstaben (`php.md` → Kennung `php`).
- Beginnt mit `# Coding-Regeln — <Anzeigename>`, direkt danach eine kurze Beschreibung (erste Zeile wird als
  Kurzbeschreibung im Indexblock von `coding_rules.md` übernommen).
- Enthält nur **projektunabhängige** Regeln (gilt für jedes Projekt mit dieser Sprache/diesem Framework);
  Projektspezifisches gehört in `coding_rules.md` § „Stack-spezifisch".
