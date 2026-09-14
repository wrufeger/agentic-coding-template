#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Querverweise in der Doku pruefen - Kuerzel wie `T3` (Task), `Q17` (Question), `ADR-14`
#        (Entscheidung), `S03` (Story) oder eine Backlog-Nummer werden staendig zitiert, sind aber reiner
#        Text: eine falsche Nummer, ein archiviertes Ziel oder ein Tippfehler faellt niemandem auf. Dieses
#        Script findet zitierte Kuerzel ohne Ziel (tote Verweise) und Ziele, die nirgends zitiert werden
#        (verwaiste Ziele), und kann fehlende Markdown-Links ergaenzen. Siehe docs/ai/README.md §
#        "Querverweise", docs/ai/checklists.md § "Doku pruefen und nachziehen". Reine Python-Stdlib.
#
# Aufruf:
#   python .claude/scripts/check-refs.py [--check] [--root <pfad>]
#       (Default) Durchsucht alle .md-Dateien unter docs/ und .templatedev/ (falls vorhanden) nach
#       Kuerzeln, prueft je Fund, ob das Ziel existiert, und meldet tote Verweise (Fundstelle Datei:Zeile)
#       sowie - als kuerzere, separate Liste - verwaiste Ziele (existieren, werden aber nirgends zitiert).
#       Schreibt nichts. Exit 0, wenn keine toten Verweise gefunden wurden (verwaiste Ziele allein sind
#       kein Fehler, nur ein Hinweis), sonst Exit 1.
#   python .claude/scripts/check-refs.py --links [--yes] [--root <pfad>]
#       Ergaenzt Markdown-Links bei Verweisen, die noch keiner sind (aus `T3` wird `[T3](tasks.md)`, aus
#       einer bereits verlinkten Stelle wird nichts). Nur Verweise mit existierendem Ziel werden verlinkt -
#       ein toter Verweis wird gemeldet, aber nicht verlinkt (ein Link ins Leere waere kein Fortschritt).
#       Je Datei/Kuerzel wird nur das ERSTE unverlinkte Vorkommen verlinkt (Konvention aus
#       docs/ai/README.md: "beim ersten Vorkommen verlinkt, danach genuegt das nackte Kuerzel") - weitere
#       Vorkommen bleiben absichtlich unangetastet. Beim Backlog-Kuerzel bleibt dabei die vorgefundene
#       Schreibweise stehen (`#42`, "Backlog 42" oder `B42`) - umschreiben auf die bevorzugte Form ist
#       Sache eines anderen Werkzeugs, nicht dieses Scripts. Zeigt immer zuerst die Trefferliste
#       (Datei:Zeile, alt -> neu) und schreibt ohne --yes NICHTS (Exit 0, dieselbe Vorsicht wie bei
#       rename-lib.py --rename-orchestrator). Erst mit --yes wird geschrieben.
#
# Kuerzel/Ziele (siehe docs/ai/README.md § "Querverweise"):
#   T<n>          Task               docs/ai/tasks.md, sonst docs/ai/tasks_archive.md
#   Q<n>          Question           docs/ai/questions.md, sonst docs/ai/questions_archive.md - im
#                                     Template-Checkout stattdessen .templatedev/questions.md (eigener
#                                     Namensraum je Repo, dasselbe Kuerzel)
#   ADR-<n>       Entscheidung       docs/project/decisions.md (erste Spalte der Tabelle)
#   S<n>          Story              docs/project/stories/S<n>-*.md (eigene Datei je Story)
#   B<n>          Backlog-Punkt      docs/ai/backlog.md (erste Spalte "ID" der Tabelle) - bevorzugte Form;
#                                     "#<n>" und "Backlog <n>" sind Altschreibweisen und werden weiterhin
#                                     erkannt, damit Altbestaende nicht durchs Raster fallen (Stand: die
#                                     Kuerzel wurden 2026 von A/F/T(Template) auf T/Q/B umgestellt, siehe
#                                     Ledger).
#
# Erkennung der Kuerzel-DEFINITIONEN (also: existiert das Ziel wirklich):
#   Task/Question: die fette Kopfzeile aus dem jeweiligen Format, z.B. "**T7 · Titel**" bzw.
#     "**Q3 · Frage**" (siehe tasks.md/questions.md) - eine bloss zitierende Fettschrift ohne " · "
#     (z.B. "laeuft als **T11**.") zaehlt nicht als Definition, nur als Zitat.
#   ADR: die erste Spalte einer Markdown-Tabellenzeile ("| 14 | ... |") in decisions.md.
#   Backlog: drei gleichwertige Definitionsformen, alle nur in den Dateien aus DEF_FILES["backlog"]
#     (docs/ai/backlog.md, .templatedev/backlog.md) gesucht - eine nummerierte Liste anderswo (Checkliste,
#     Skill-Anleitung) ist KEINE Backlog-Definition:
#       1. Tabellenzeile ("| 42 | ... |", so fuehrt z.B. bandliste seinen Backlog).
#       2. Einzeiler unter "Erledigt" ("- 21 · ..." - Bindestrich, Zahl, Mittelpunkt).
#       3. Nummerierte Liste fuer offene Punkte ("22. -> machen: ..." - der Pfeil-Marker ist ueblich, aber
#          nicht Teil des Musters, da er nicht immer vorkommt).
#   Story: der Dateiname selbst (docs/project/stories/S<n>-*.md).
#
# Ignorier-Marker (fuer Formbeschreibungen, die Kuerzel nur als Beispiel nennen, z.B. "Fragen laufen unter
#   `Q1`, `Q2`, …" in questions.md - kein echtes Zitat/keine echte Definition): eine Zeile mit
#   "<!-- check-refs:ignore -->" schaltet die naechste Zeile komplett aus (weder Zitat noch Definition wird
#   dort erkannt); ein Block zwischen "<!-- check-refs:ignore-start -->" und
#   "<!-- check-refs:ignore-end -->" (je eigene Zeile) schaltet alles dazwischen aus. Die Marker-Zeilen
#   selbst zaehlen ebenfalls nie als Fund. Gilt fuer alle Kategorien gleichermassen.
#
# Maskierung beim Suchen nach Zitaten (bewusst ANDERS als rename-lib.py:_find_masked_spans_md): Fenced Code
#   Blocks, eingerueckte Codebloecke, URLs und plausible Pfadangaben werden genauso ausmaskiert (siehe
#   _masked_spans_for_scan, nutzt dieselben Regex/Hilfsfunktionen aus rename-lib.py). NICHT ausmaskiert wird
#   Inline-Code in einzelnen Backticks: ein Praxis-Check gegen ein echtes Projekt zeigte, dass die meisten
#   echten Zitate genau dort stehen (z.B. "`T9`" in einer Tabellenzelle) - eine Backtick-Maskierung wie bei
#   der Namensersetzung wuerde die Mehrheit der echten Verweise unsichtbar machen.
#
# Bekannte Grenzen (kein echter Markdown-Parser, nur Regex mit Wortgrenzen):
#   - "Klasse T3" oder "Vitamin B12" oder ein aehnlicher Zufallstreffer ausserhalb dieses Doku-Schemas wird
#     als Task T3 bzw. Backlog-Punkt B12 gezaehlt, wenn das Kuerzel an der Stelle wie ein echtes aussieht
#     (Wortgrenze davor/danach). In der Praxis (Projektdoku, kein Fliesstext ueber Autoteile/Vitamine) ist
#     das selten - im Testlauf gegen ein reales Projekt (siehe Bericht) wurden Stichproben von Hand
#     nachgeprueft.
#   - Backlog-Nummern sind bloss Ziffern und damit das mehrdeutigste Kuerzel; erkannt werden die bevorzugte
#     Form "B<n>" sowie die beiden Altschreibweisen "#<n>" (nicht direkt hinter einem Wortzeichen oder "/",
#     damit "reponame#123"/URLs nicht mitzaehlen) und "Backlog <n>"/"Backlog-<n>".
#   - .templatedev/ enthaelt Arbeitsnotizen der Template-Entwicklung, die auch ueber ANDERE Projekte
#     sprechen (Testlaeufe) und dabei deren ADR-/Task-Nummern zitieren koennen - fuer dieses Repo sind
#     das dann korrekt gemeldete tote Verweise (das Ziel existiert in DIESEM Repo nicht), auch wenn sie im
#     Ursprungsprojekt gueltig waren.
#
# Exit-Codes: 0 = ok (auch "nichts gefunden", auch die Trefferliste von --links ohne --yes), 1 = --check hat
#   mindestens einen toten Verweis gefunden. main() laeuft komplett in try/except, kein Traceback nach aussen.

import argparse
import bisect
import importlib.util
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
}


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _load_rename_lib(root: Path):
    """Laedt rename-lib.py per importlib (gleiches Muster wie sync-config.py:_load_module) - liefert die
    Fence-/Pfad-Erkennung fuer die Maskierung, ohne sie hier zu duplizieren. None, wenn die Datei fehlt
    (sollte laut finish-setup.py nie vorkommen, da rename-lib.py dauerhaft bestehen bleibt) - dann laeuft
    die Maskierung ohne Fence-/Pfaderkennung weiter, statt abzustuerzen."""
    path = root / ".claude" / "scripts" / "rename-lib.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_check_refs_rename_lib", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dateien einsammeln
# ---------------------------------------------------------------------------


def _iter_md_files(root: Path):
    """Alle .md-Dateien unter docs/ und .templatedev/ (falls vorhanden), root-relative Posix-Pfade,
    sortiert fuer eine stabile Ausgabe."""
    bases = [root / "docs"]
    templatedev = root / ".templatedev"
    if templatedev.is_dir():
        bases.append(templatedev)
    found = []
    for base in bases:
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for fname in filenames:
                if fname.lower().endswith(".md"):
                    found.append(Path(dirpath) / fname)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def _read_text_or_none(fp: Path):
    """Wie rename-lib.py:_read_text_or_none (Bytes lesen, Binaerdatei/kaputtes UTF-8 -> None) - hier
    dupliziert, damit dieses Script auch ohne geladenes rename-lib.py (siehe _load_rename_lib) lesen kann."""
    try:
        raw = fp.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# Maskierung (Fence/Pfad/URL wie rename-lib.py, Inline-Code bewusst NICHT - siehe Kopfkommentar)
# ---------------------------------------------------------------------------


def _masked_spans_for_scan(text: str, rename_mod):
    lines = text.splitlines(keepends=True)
    offsets = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    spans = []

    if rename_mod is not None:
        protected_line_idx = set()
        fence_char, fence_len, fence_start = None, 0, None
        for i, raw in enumerate(lines):
            line = raw.rstrip("\r\n")
            if fence_char is None:
                m = rename_mod._FENCE_OPEN_RE.match(line)
                if m:
                    marker = m.group(1)
                    fence_char, fence_len, fence_start = marker[0], len(marker), i
            elif rename_mod._is_fence_close(line, fence_char, fence_len):
                for j in range(fence_start, i + 1):
                    protected_line_idx.add(j)
                fence_char = None
        if fence_char is not None:
            for j in range(fence_start, len(lines)):
                protected_line_idx.add(j)

        in_indented_block = False
        prev_blank = True
        for i, raw in enumerate(lines):
            if i in protected_line_idx:
                in_indented_block = False
                prev_blank = raw.strip(" \t\r\n") == ""
                continue
            is_blank = raw.strip(" \t\r\n") == ""
            if is_blank:
                prev_blank = True
                continue
            stripped = raw.lstrip(" \t")
            indent = raw[: len(raw) - len(stripped)]
            is_indented = "\t" in indent or len(indent) >= 4
            if is_indented and (in_indented_block or prev_blank):
                protected_line_idx.add(i)
                in_indented_block = True
            else:
                in_indented_block = False
            prev_blank = False

        spans.extend((offsets[i], offsets[i] + len(lines[i])) for i in protected_line_idx)

    for m in re.finditer(r"(?:https?://|www\.)\S+", text):
        spans.append(m.span())
    if rename_mod is not None:
        for m in re.finditer(r"\S*/\S+", text):
            if rename_mod._looks_like_path(m.group(0)):
                spans.append(m.span())

    if rename_mod is not None:
        return rename_mod._merge_spans(spans)
    return _merge_spans(spans)


def _merge_spans(spans):
    """Sortiert/verschmilzt Zeichenspannen - eigene Kopie statt rename-lib.py:_merge_spans, damit dieses
    Script auch ohne geladenes rename-lib.py (siehe _load_rename_lib) funktioniert."""
    spans = sorted((s for s in spans if s[0] < s[1]), key=lambda s: s[0])
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _pos_in_spans(pos: int, spans) -> bool:
    for start, end in spans:
        if start <= pos < end:
            return True
        if start > pos:
            break
    return False


# ---------------------------------------------------------------------------
# Ignorier-Marker (siehe Kopfkommentar) - gilt fuer Zitate UND Definitionen gleichermassen.
# ---------------------------------------------------------------------------

_IGNORE_LINE_RE = re.compile(r"^\s*<!--\s*check-refs:ignore\s*-->\s*$")
_IGNORE_START_RE = re.compile(r"^\s*<!--\s*check-refs:ignore-start\s*-->\s*$")
_IGNORE_END_RE = re.compile(r"^\s*<!--\s*check-refs:ignore-end\s*-->\s*$")


def _ignore_spans(text: str):
    """Zeichenspannen, die per Marker ausgeschaltet sind: die Marker-Zeile(n) selbst, die naechste Zeile
    nach einem Einzeiler-Marker, bzw. alles zwischen ignore-start/ignore-end (inklusive beider Marker)."""
    lines = text.splitlines(keepends=True)
    offsets = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    ignored_idx = set()
    in_block = False
    skip_next = False
    for i, raw0 in enumerate(lines):
        raw = raw0.rstrip("\r\n")
        if skip_next:
            ignored_idx.add(i)
            skip_next = False
            continue
        if in_block:
            ignored_idx.add(i)
            if _IGNORE_END_RE.match(raw):
                in_block = False
            continue
        if _IGNORE_START_RE.match(raw):
            ignored_idx.add(i)
            in_block = True
            continue
        if _IGNORE_LINE_RE.match(raw):
            ignored_idx.add(i)
            skip_next = True
            continue

    return [(offsets[i], offsets[i] + len(lines[i])) for i in ignored_idx]


# ---------------------------------------------------------------------------
# Kuerzel-Muster (Zitat) je Kategorie - siehe Kopfkommentar fuer die Abwaegung.
# ---------------------------------------------------------------------------

CATEGORIES = {
    "task": {
        "label": "Task",
        "pattern": re.compile(r"(?<![A-Za-zÄÖÜäöüß0-9_])T(\d{1,4})\b"),
    },
    "question": {
        "label": "Question",
        "pattern": re.compile(r"(?<![A-Za-zÄÖÜäöüß0-9_])Q(\d{1,4})\b"),
    },
    "adr": {
        "label": "Entscheidung",
        "pattern": re.compile(r"\bADR-(\d{1,4})\b"),
    },
    "story": {
        "label": "Story",
        "pattern": re.compile(r"(?<![A-Za-zÄÖÜäöüß0-9_])S(\d{1,3})\b"),
    },
    "backlog": {
        "label": "Backlog",
        # Bevorzugt "B<n>", daneben weiterhin die beiden Altschreibweisen "#<n>"/"Backlog <n>" (siehe
        # Kopfkommentar) - drei Gruppen, collect_citations nimmt die erste, die nicht None ist.
        "pattern": re.compile(
            r"(?<![A-Za-zÄÖÜäöüß0-9_/])#(\d{1,4})\b"
            r"|(?<![A-Za-zÄÖÜäöüß0-9_])B(\d{1,4})\b"
            r"|\bBacklog[- ](\d{1,4})\b"
        ),
    },
}

# Definitions-Muster fuer Task/Question: die fette Kopfzeile "**<Buchstabe><n> ·" (siehe Kopfkommentar).
# Eine bloss zitierende Fettschrift ohne " ·" (z.B. "laeuft als **T11**.") ist keine Definition.
_BOLD_DOT_RE = {
    "task": re.compile(r"\*\*T(\d{1,4})\s*(?:·|$)", re.MULTILINE),
    "question": re.compile(r"\*\*Q(\d{1,4})\s*(?:·|$)", re.MULTILINE),
}
_TABLE_ID_RE = re.compile(r"^\|\s*(\d{1,6})\s*\|", re.MULTILINE)
# Zweite Definitionsform fuer Backlog-Punkte: erledigte Punkte wandern als Einzeiler "- <n> · ..." in einen
# Abschnitt "Erledigt" statt in der nummerierten/Tabellenform zu bleiben (siehe Kopfkommentar).
_BACKLOG_DONE_RE = re.compile(r"^-\s*(\d{1,6})\s*·", re.MULTILINE)
# Dritte Definitionsform: offene Punkte als nummerierte Liste "22. -> machen: ..." (der Pfeil-Marker steht
# oft, aber nicht immer dahinter - deshalb nur bis zum Punkt+Leerzeichen gematcht). NUR fuer die Dateien aus
# DEF_FILES["backlog"] verwendet (siehe collect_definitions) - eine nummerierte Liste in einer Checkliste
# oder Skill-Anleitung ("7. Schritt ...") ist dort KEINE Backlog-Definition.
_BACKLOG_NUMBERED_RE = re.compile(r"^(\d{1,6})\.\s", re.MULTILINE)
_STORY_FILE_RE = re.compile(r"^S(\d{1,4})-.+\.md$", re.IGNORECASE)

DEF_FILES = {
    "task": ["docs/ai/tasks.md", "docs/ai/tasks_archive.md"],
    # Question-Definitionen: normales Projekt (questions.md/-archive) UND Template-Checkout
    # (.templatedev/questions.md) - dasselbe Kuerzel Q<n>, aber je Repo nur eine der beiden Quellen mit
    # echtem Inhalt (siehe Kopfkommentar "eigener Namensraum je Repo").
    "question": ["docs/ai/questions.md", "docs/ai/questions_archive.md", ".templatedev/questions.md"],
    "adr": ["docs/project/decisions.md"],
    # Ebenfalls je Repo nur eine Quelle mit echtem Inhalt: normales Projekt vs. Template-Checkout.
    "backlog": ["docs/ai/backlog.md", ".templatedev/backlog.md"],
}
STORIES_DIR = "docs/project/stories"


# ---------------------------------------------------------------------------
# Definitionen einsammeln
# ---------------------------------------------------------------------------


def collect_definitions(root: Path, files_by_rel: dict, excluded_by_rel: dict = None):
    """Liefert (definitions, self_spans). 'definitions' ist Kategorie -> {nummer: ziel_relpath}.
    'self_spans' ist Kategorie -> Menge (rel, start) der Zeichenposition, an der eine Definition selbst wie
    ein Zitat aussieht (siehe _BOLD_DOT_RE) - wird beim Zitat-Zaehlen ausgeschlossen, sonst waere jede
    Definition automatisch ihr eigenes Zitat und nie 'verwaist'. 'excluded_by_rel' (maskierte Bereiche +
    Ignorier-Marker, siehe _ignore_spans) macht eine Stelle unsichtbar - weder Zitat noch Definition."""
    excluded_by_rel = excluded_by_rel or {}
    definitions = {key: {} for key in CATEGORIES}
    self_spans = {key: set() for key in _BOLD_DOT_RE}

    for key, pat in _BOLD_DOT_RE.items():
        for rel in DEF_FILES[key]:
            content = files_by_rel.get(rel)
            if content is None:
                continue
            excluded = excluded_by_rel.get(rel, [])
            for m in pat.finditer(content):
                if _pos_in_spans(m.start(), excluded):
                    continue
                n = int(m.group(1))
                definitions[key].setdefault(n, rel)
                letter_start = m.start() + 2  # Position direkt nach "**"
                self_spans[key].add((rel, letter_start))

    for key in ("adr", "backlog"):
        for rel in DEF_FILES[key]:
            content = files_by_rel.get(rel)
            if content is None:
                continue
            excluded = excluded_by_rel.get(rel, [])
            for m in _TABLE_ID_RE.finditer(content):
                if _pos_in_spans(m.start(), excluded):
                    continue
                n = int(m.group(1))
                definitions[key].setdefault(n, rel)
            if key == "backlog":
                for extra_pat in (_BACKLOG_DONE_RE, _BACKLOG_NUMBERED_RE):
                    for m in extra_pat.finditer(content):
                        if _pos_in_spans(m.start(), excluded):
                            continue
                        n = int(m.group(1))
                        definitions[key].setdefault(n, rel)

    stories_dir = root / STORIES_DIR
    if stories_dir.is_dir():
        try:
            entries = sorted(stories_dir.iterdir())
        except OSError:
            entries = []
        for fp in entries:
            if not fp.is_file():
                continue
            m = _STORY_FILE_RE.match(fp.name)
            if m:
                n = int(m.group(1))
                rel = (stories_dir / fp.name).relative_to(root).as_posix()
                definitions["story"].setdefault(n, rel)

    return definitions, self_spans


# ---------------------------------------------------------------------------
# Zitate einsammeln
# ---------------------------------------------------------------------------


def collect_citations(files_by_rel: dict, masked_by_rel: dict, self_spans: dict):
    """Liefert eine Liste von Treffern: dict mit rel, line, col, start, end, text, kategorie, nummer -
    Definitionszeilen (self_spans) und maskierte Bereiche sind bereits ausgeschlossen."""
    hits = []
    for rel, content in files_by_rel.items():
        if not content:
            continue
        masked = masked_by_rel.get(rel, [])
        lines = content.splitlines()
        line_offsets = []
        pos = 0
        for ln in content.splitlines(keepends=True):
            line_offsets.append(pos)
            pos += len(ln)

        for key, cfg in CATEGORIES.items():
            for m in cfg["pattern"].finditer(content):
                start, end = m.start(), m.end()
                if _pos_in_spans(start, masked):
                    continue
                if (rel, start) in self_spans.get(key, ()):
                    continue
                groups = m.groups()
                n_txt = next((g for g in groups if g is not None), None)
                if n_txt is None:
                    continue
                number = int(n_txt)

                line_idx = max(0, min(bisect.bisect_right(line_offsets, start) - 1, len(lines) - 1))
                col = start - line_offsets[line_idx] if lines else 0
                hits.append(
                    {
                        "rel": rel,
                        "line": line_idx + 1,
                        "col": col,
                        "start": start,
                        "end": end,
                        "text": m.group(0),
                        "kategorie": key,
                        "nummer": number,
                    }
                )
    hits.sort(key=lambda h: (h["rel"], h["start"]))
    return hits


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def run_check(root: Path, files_by_rel: dict, masked_by_rel: dict) -> int:
    definitions, self_spans = collect_definitions(root, files_by_rel, masked_by_rel)
    hits = collect_citations(files_by_rel, masked_by_rel, self_spans)

    dead = []
    cited = {key: set() for key in CATEGORIES}
    for h in hits:
        key, n = h["kategorie"], h["nummer"]
        if n in definitions[key]:
            cited[key].add(n)
        else:
            dead.append(h)

    orphans = []
    for key, cfg in CATEGORIES.items():
        for n, rel in sorted(definitions[key].items()):
            if n not in cited[key]:
                orphans.append((key, n, rel))

    lines = []
    if dead:
        lines.append(f"Tote Verweise ({len(dead)}):")
        for h in dead:
            label = CATEGORIES[h["kategorie"]]["label"]
            lines.append(f"  {h['rel']}:{h['line']}  {h['text']} ({label}) — Ziel nicht gefunden")
    else:
        lines.append("Tote Verweise: keine.")

    lines.append("")
    if orphans:
        lines.append(f"Verwaiste Ziele ({len(orphans)}) — existieren, werden aber nirgends zitiert:")
        for key, n, rel in orphans:
            label = CATEGORIES[key]["label"]
            lines.append(f"  {label} {n} ({rel})")
    else:
        lines.append("Verwaiste Ziele: keine.")

    total_defs = sum(len(d) for d in definitions.values())
    lines.append("")
    lines.append(
        f"Zusammenfassung: {len(files_by_rel)} Dateien geprüft, {len(hits)} Zitate, {total_defs} "
        f"Definitionen, {len(dead)} tot, {len(orphans)} verwaist."
    )
    print("\n".join(lines))
    return 1 if dead else 0


# ---------------------------------------------------------------------------
# --links
# ---------------------------------------------------------------------------


def _already_linked(text: str, start: int, end: int) -> bool:
    i = start
    while i > 0 and text[i - 1] in "`*":
        i -= 1
    if i == 0 or text[i - 1] != "[":
        return False
    j = end
    while j < len(text) and text[j] in "`*":
        j += 1
    return text[j : j + 2] == "]("


def _extend_wrap(text: str, start: int, end: int):
    """Bezieht einen unmittelbar umschliessenden Backtick- oder Fett-Marker mit ein, damit aus `` `T9` ``
    `` [`T9`](ziel) `` wird statt `` `[T9]`(ziel) ``."""
    if start >= 2 and text[start - 2 : start] == "**" and text[end : end + 2] == "**":
        return start - 2, end + 2
    if start >= 1 and text[start - 1] == "`" and text[end : end + 1] == "`":
        return start - 1, end + 1
    return start, end


def _rel_link(source_rel: str, target_rel: str) -> str:
    """Relativer Pfad vom Ordner der Fundstelle zum Ziel, Posix-Trenner - kein Anker (siehe Kopfkommentar:
    keines der Ziele ist eine echte, stabile Ueberschrift, ein erfundener Anker waere falsch)."""
    src_dir = os.path.dirname(source_rel)
    rel = os.path.relpath(target_rel, start=src_dir if src_dir else ".")
    return rel.replace(os.sep, "/")


def run_links(root: Path, files_by_rel: dict, masked_by_rel: dict, yes: bool) -> int:
    definitions, self_spans = collect_definitions(root, files_by_rel, masked_by_rel)
    hits = collect_citations(files_by_rel, masked_by_rel, self_spans)

    seen_per_file = set()  # (rel, kategorie, nummer) - nur das erste unverlinkte Vorkommen bekommt einen Link
    edits_by_file = {}
    skipped_dead = 0
    skipped_already = 0

    for h in hits:
        key, n, rel = h["kategorie"], h["nummer"], h["rel"]
        target_rel = definitions[key].get(n)
        if target_rel is None:
            skipped_dead += 1
            continue
        if target_rel == rel:
            # Zitat steht bereits in der Zieldatei selbst (z.B. die eigene Ueberschrift einer Story) - ein
            # Link ohne Anker (siehe Kopfkommentar) waere dort ein Sprung ins Leere/auf sich selbst.
            continue
        content = files_by_rel[rel]
        s, e = _extend_wrap(content, h["start"], h["end"])
        if _already_linked(content, s, e):
            skipped_already += 1
            continue
        if (rel, key, n) in seen_per_file:
            continue
        seen_per_file.add((rel, key, n))
        link_target = _rel_link(rel, target_rel)
        edits_by_file.setdefault(rel, []).append((s, e, content[s:e], link_target))

    if not edits_by_file:
        print("Nichts zu verlinken — keine unverlinkten Zitate mit gültigem Ziel gefunden.")
        if skipped_dead:
            print(f"({skipped_dead} Zitate übersprungen: totes Ziel, wird nicht verlinkt.)")
        return 0

    total = sum(len(v) for v in edits_by_file.values())
    print(f"Trefferliste ({total} Verlinkungen in {len(edits_by_file)} Dateien):")
    for rel in sorted(edits_by_file):
        for s, e, old_text, target in sorted(edits_by_file[rel]):
            print(f"  {rel}: {old_text} -> [{old_text}]({target})")
    if skipped_dead:
        print(f"Übersprungen (totes Ziel, nicht verlinkt): {skipped_dead}")

    if not yes:
        print("")
        print("Nichts geschrieben — vorher committen (git diff bleibt dann prüfbar), danach zur "
              "Bestätigung dieselbe Zeile mit --yes wiederholen.")
        return 0

    for rel, edits in edits_by_file.items():
        fp = root / rel
        content = files_by_rel[rel]
        pieces = []
        pos = 0
        for s, e, old_text, target in sorted(edits, key=lambda x: x[0]):
            pieces.append(content[pos:s])
            pieces.append(f"[{old_text}]({target})")
            pos = e
        pieces.append(content[pos:])
        fp.write_bytes("".join(pieces).encode("utf-8"))
    print("")
    print("Geschrieben — Ergebnis mit 'git diff' prüfen.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _run(argv) -> int:
    parser = argparse.ArgumentParser(description="Prueft Querverweise (T<n>/Q<n>/ADR-<n>/S<n>/B<n>).")
    parser.add_argument("--check", action="store_true", help="Nur pruefen (Default).")
    parser.add_argument("--links", action="store_true", help="Fehlende Markdown-Links ergaenzen.")
    parser.add_argument("--yes", action="store_true", help="Mit --links: tatsaechlich schreiben.")
    parser.add_argument("--root", default=None, help="Repo-Wurzel (Default: CLAUDE_PROJECT_DIR o.ae.).")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else _find_root()
    if not root.is_dir():
        print(f"Fehler: Wurzel {root} existiert nicht.", file=sys.stderr)
        return 2

    rename_mod = _load_rename_lib(root)
    md_files = _iter_md_files(root)
    files_by_rel = {}
    for fp in md_files:
        content = _read_text_or_none(fp)
        if content is not None:
            files_by_rel[fp.relative_to(root).as_posix()] = content
    masked_by_rel = {
        rel: _merge_spans(_masked_spans_for_scan(content, rename_mod) + _ignore_spans(content))
        for rel, content in files_by_rel.items()
    }

    if args.links:
        return run_links(root, files_by_rel, masked_by_rel, args.yes)
    return run_check(root, files_by_rel, masked_by_rel)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"check-refs: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
