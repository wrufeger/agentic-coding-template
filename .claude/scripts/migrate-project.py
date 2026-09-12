#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Weg 2 ("Projekt nachruesten") von "nur ergaenzen" auf "auf Template-Struktur migrieren" erweitern.
#        Laeuft IM ZIELREPO (nicht im Template-Checkout), nachdem consume-template.py bereits dorthin
#        kopiert hat. Erkennt vorhandene KI-Arbeitsordner (z.B. fable/, ai/, docs/ki/) samt ihrer
#        Arbeitsdateien (Board/Aufgaben/Fragen/Ledger/Backlog/Checklisten unter beliebigem Namen) und
#        schlaegt vor, sie nach docs/ai/<template-name> zu verschieben; erkennt Dateien, die im Ziel UND im
#        Template existieren und sich inhaltlich unterscheiden (Zusammenfuehren noetig); erkennt einen im
#        Projekt fest verwendeten Orchestrator-Rufnamen (z.B. "Fable") und kann ihn projektweit durch den
#        neuen Namen ersetzen. Siehe .claude/skills/consume-template/SKILL.md,
#        docs/ai/checklists.md § "Projekt nachruesten". Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf:
#   python .claude/scripts/migrate-project.py --plan (Default)
#       Erkennt und zeigt den Migrationsplan (Verschieben/Zusammenfuehren/Orchestrator-Name/leere
#       Altordner), schreibt nichts. Exit 0, auch wenn nichts zu tun ist.
#   python .claude/scripts/migrate-project.py --apply
#       Fuehrt den Plan aus: verschiebt Arbeitsdateien per 'git mv' nach docs/ai/<template-name>
#       (Historie bleibt erhalten), loest Zielkollisionen auf (inhaltsgleich -> Altdatei geloescht,
#       unterschiedlich -> Altdatei als docs/ai/<name>.alt.md danebengelegt), fuehrt danach automatisch die
#       Orchestrator-Umbenennung aus, wenn ein Name per --rename-orchestrator uebergeben oder in CONFIG.md
#       § "Alter Orchestrator-Name" gesetzt ist. Vorbedingung: sauberer Arbeitsbaum (git status --porcelain
#       leer) - sonst Exit 2, damit die Migration bei Bedarf rueckgaengig gemacht werden kann. Kein Git-Repo
#       -> Exit 2.
#   python .claude/scripts/migrate-project.py --rename-orchestrator ALT=NEU
#       Nur die Namensersetzung (auch einzeln nutzbar, ohne Struktur-Migration). Schreibt in jede Textdatei
#       des Repos und hat deshalb dieselbe Vorbedingung wie --apply: Git-Repo, sauberer Arbeitsbaum, sonst
#       Exit 2. Ausgelassen werden CONFIG.md, .claude/scripts/*.py, Binaerdateien und die Ordner aus
#       RENAME_SKIP_DIR_NAMES (node_modules, .venv, dist, build, ...). Zeilenenden und BOM bleiben erhalten.
#       Mit --plan kombiniert wird nur gezeigt, was ersetzt wuerde (kein Schreibzugriff).
#   python .claude/scripts/migrate-project.py --status
#       Kurzuebersicht: was ist bereits Template-konform, was nicht (Anzahl erkannter Altordner/
#       Verschiebungen/Zusammenfuehrungen, Orchestrator-Kandidaten).
#
# Erkennung KI-Arbeitsordner (find_ai_dirs): Verzeichnisse bis Tiefe 2 (ohne .git, node_modules, .venv,
# dist, build, .claude), die mindestens eine Datei mit bekanntem Arbeitsdatei-Namen enthalten (siehe
# TARGET_PATTERNS) und dabei entweder selbst {fable, ai, ki, agent, agents, assistant, kiki, copilot}
# heissen - oder, bei beliebigem Namen, mindestens zwei solche Dateien haben. Der Name allein reicht
# bewusst nicht: ein echter Quellcode-Ordner src/ai/ oder Fachdoku unter docs/ki/ wuerde sonst mitwandern.
# Verschoben werden nur .md-Dateien direkt im Ordner (keine Unterordner, kein Quellcode).
# docs/ai/ selbst gilt nie als "alt".
#
# Prioritaetsregeln bei "Zusammenfuehren" (macht der Assistent, nicht dieses Script) - siehe PRIORITY_RULES:
# .claude/**, AGENTS.md, CLAUDE.md, docs/ai/checklists.md, docs/ai/README.md -> Template gewinnt;
# docs/ai/-Arbeitsdateien -> Template-Struktur, Projekt-Inhalt; docs/project/** -> Projekt gewinnt (Ausnahme
# coding_rules.md: strengere Regel gewinnt); README.md/.gitignore -> Projekt gewinnt, Template ergaenzt.
#
# Exit-Codes: 0 = ok (auch "nichts zu tun"), 2 = Vorbedingungsfehler (kein Git, unsauberer Arbeitsbaum,
# ungueltiges --rename-orchestrator, Zielverzeichnis sieht nicht nach einem Projekt aus diesem Template aus).
# Ein Fehler dieses Scripts darf nie mit Traceback nach aussen dringen: main() laeuft komplett in
# try/except, Fehlermeldungen auf stderr.

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Dieses Script laedt template-update.py/new-project.py aus dem Ziel dynamisch nach (siehe _load_module) -
# ohne dies wuerde ein reiner --plan-Lauf ein __pycache__/ im Ziel hinterlassen und damit "git status
# --porcelain" verschmutzen (blockiert dann faelschlich die Vorbedingung von --apply).
sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# Erkennung KI-Arbeitsordner + Arbeitsdateien
# ---------------------------------------------------------------------------

EXCLUDE_DIR_NAMES = {".git", "node_modules", ".venv", "dist", "build", ".claude"}
KNOWN_DIR_NAMES = {"fable", "ai", "ki", "agent", "agents", "assistant", "kiki", "copilot"}

# Reihenfolge wichtig: spezifischere Ziele (Archive) zuerst pruefen, sonst faengt z.B. "aufgaben_archiv"
# schon das "aufgaben"-Muster von tasks.md ab.
CHECK_ORDER = [
    "tasks_archive.md",
    "questions_archive.md",
    "board.md",
    "tasks.md",
    "questions.md",
    "ledger.md",
    "backlog.md",
    "checklists.md",
]

TARGET_PATTERNS = {
    "board.md": [r"board", r"uebersicht", r"übersicht", r"overview", r"start", r"einstieg"],
    "tasks.md": [r"aufgaben", r"tasks", r"todo"],
    "tasks_archive.md": [
        r"aufgaben_archiv", r"tasks_archive", r"todo_archiv", r".*_erledigt",
    ],
    "questions.md": [r"fragen", r"questions"],
    "questions_archive.md": [r"fragen_archiv", r"questions_archive"],
    "ledger.md": [r"ledger", r"journal", r"chronik", r"verlauf", r"chatlog"],
    "backlog.md": [r"backlog", r"umbau", r"umbauliste", r"ideen", r"vorschlaege", r"vorschläge"],
    "checklists.md": [r"checkliste", r"checklists"],
}


def match_target(filename: str):
    """Ordnet einen Dateinamen einer Template-Zieldatei zu (siehe TARGET_PATTERNS), oder None."""
    p = Path(filename)
    if p.suffix.lower() != ".md":
        return None
    norm = p.stem.lower().lstrip("@").replace("-", "_")
    for target in CHECK_ORDER:
        for pat in TARGET_PATTERNS[target]:
            if re.search(pat, norm):
                return target
    return None


def is_ai_dir(dir_path: Path) -> bool:
    """Ein Ordner gilt nur dann als KI-Arbeitsordner, wenn er auch wirklich Arbeitsdateien enthaelt - ein
    bekannter Name allein reicht nicht, sonst wuerde ein echter Quellcode-Ordner (src/ai/, agents/) oder
    Fachdoku unter docs/ki/ mitgerissen und nach docs/ai/ verschoben."""
    needed = 1 if dir_path.name.lower() in KNOWN_DIR_NAMES else 2
    count = 0
    try:
        for f in dir_path.iterdir():
            if f.is_file() and match_target(f.name):
                count += 1
                if count >= needed:
                    return True
    except OSError:
        pass
    return False


def find_ai_dirs(root: Path):
    """Verzeichnisse bis Tiefe 2 (root-relativ), die wie ein alter KI-Arbeitsordner aussehen. docs/ai/
    selbst wird nie gemeldet."""
    result = []

    def walk(dir_path: Path, depth: int):
        try:
            children = sorted(dir_path.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in EXCLUDE_DIR_NAMES:
                continue
            rel = child.relative_to(root).as_posix()
            if rel == "docs/ai":
                continue
            if is_ai_dir(child):
                result.append(child)
            if depth < 2:
                walk(child, depth + 1)

    walk(root, 1)
    return result


def scan_ai_dir(ai_dir: Path):
    """Dateien eines KI-Ordners -> (matched: target->[Path], unmatched: [Path], in_unterordnern: [Path]).

    Nur die direkten Dateien werden zum Verschieben vorgesehen. Markdown in Unterordnern (typisch: ein
    `archiv/`) wird NICHT automatisch verschoben - die Struktur dort ist projektspezifisch und eine
    Zuordnung waere geraten. Solche Dateien werden aber gemeldet, damit sie nicht stillschweigend
    liegenbleiben, waehrend der Ordner ringsum leer wird."""
    matched, unmatched, in_unterordnern = {}, [], []
    try:
        children = sorted(ai_dir.iterdir())
    except OSError:
        return matched, unmatched, in_unterordnern
    for f in children:
        if f.is_dir():
            if f.name in EXCLUDE_DIR_NAMES:
                continue
            try:
                for sub in sorted(f.rglob("*.md")):
                    if sub.is_file():
                        in_unterordnern.append(sub)
            except OSError:
                pass
            continue
        if not f.is_file():
            continue
        target = match_target(f.name)
        if target:
            matched.setdefault(target, []).append(f)
        elif f.suffix.lower() == ".md":
            # Nur Markdown gilt als moegliche Arbeitsdatei. Alles andere (Quellcode, Bilder, Konfiguration)
            # bleibt liegen - es waere sonst nach docs/ai/ verschoben worden.
            unmatched.append(f)
    return matched, unmatched, in_unterordnern


def build_plan(root: Path):
    """Liefert (ai_dirs, moves, conflicts, in_unterordnern). moves: Liste (src, dest, note).
    conflicts: target -> Liste zusaetzlicher Kandidaten (die nicht verschoben, sondern als unzugeordnet
    gefuehrt werden)."""
    ai_dirs = find_ai_dirs(root)
    target_candidates = {}
    unassigned = []
    in_unterordnern = []
    for d in ai_dirs:
        matched, unmatched, sub_md = scan_ai_dir(d)
        for target, paths in matched.items():
            target_candidates.setdefault(target, []).extend(paths)
        unassigned.extend(unmatched)
        in_unterordnern.extend(sub_md)

    moves = []
    conflicts = {}
    docs_ai = root / "docs" / "ai"
    for target, paths in sorted(target_candidates.items()):
        paths_sorted = sorted(paths, key=lambda p: p.as_posix())
        primary = paths_sorted[0]
        moves.append((primary, docs_ai / target, None))
        if len(paths_sorted) > 1:
            rest = paths_sorted[1:]
            conflicts[target] = rest
            unassigned.extend(rest)

    for p in sorted(set(unassigned), key=lambda p: p.as_posix()):
        moves.append((p, docs_ai / p.name, "unzugeordnet"))

    return ai_dirs, moves, conflicts, sorted(set(in_unterordnern), key=lambda p: p.as_posix())


def compute_empty_dirs(root: Path, ai_dirs, moved_set=None):
    """Altordner, die nach den geplanten/ausgefuehrten Verschiebungen keine Datei mehr enthalten (rekursiv
    geprueft, nie automatisch geloescht)."""
    empty = []
    for d in ai_dirs:
        remaining = False
        for fp in d.rglob("*"):
            if fp.is_file() and (moved_set is None or fp not in moved_set):
                remaining = True
                break
        if not remaining:
            empty.append(d.relative_to(root).as_posix())
    return sorted(empty)


# ---------------------------------------------------------------------------
# Zusammenfuehren-Kandidaten (Ziel und Template existieren, Inhalt unterscheidet sich)
# ---------------------------------------------------------------------------

MERGE_ROOT_FILES = ["AGENTS.md", "CLAUDE.md", "README.md", ".gitignore"]
# docs/ai gehoert dazu, weil die Prioritaetsregeln unten ausdruecklich docs/ai/checklists.md und
# docs/ai/README.md nennen - ohne den Eintrag wuerden genau diese Dateien nie als "zusammenfuehren" gemeldet.
MERGE_DIRS = [".claude/agents", ".claude/skills", "docs/ai", "docs/project"]

PRIORITY_RULES = """.claude/**, AGENTS.md, CLAUDE.md, docs/ai/checklists.md, docs/ai/README.md  -> Template gewinnt
docs/ai/ (Arbeitsdateien: board, tasks, questions, ledger, backlog)          -> Template-Struktur,
   Projekt-Inhalt
docs/project/**                                                             -> Projekt gewinnt
docs/project/coding_rules.md                                                -> strengere Regel gewinnt
README.md, .gitignore                                                       -> Projekt gewinnt,
   Template-Anteile werden ergaenzt"""


def priority_label(rel_path: str) -> str:
    if rel_path in ("AGENTS.md", "CLAUDE.md", "docs/ai/checklists.md", "docs/ai/README.md") or rel_path.startswith(".claude/"):
        return "Template gewinnt"
    if rel_path == "docs/project/coding_rules.md":
        return "strengere Regel gewinnt"
    if rel_path.startswith("docs/project/"):
        return "Projekt gewinnt"
    if rel_path.startswith("docs/ai/"):
        return "Template-Struktur, Projekt-Inhalt"
    if rel_path in ("README.md", ".gitignore"):
        return "Projekt gewinnt, ergaenzt"
    return "Projekt gewinnt"


def find_merge_candidates(root: Path):
    candidates = []
    for rel in MERGE_ROOT_FILES:
        if (root / rel).is_file():
            candidates.append(rel)
    for d in MERGE_DIRS:
        dp = root / d
        if not dp.is_dir():
            continue
        for fp in sorted(dp.rglob("*")):
            if fp.is_file():
                candidates.append(fp.relative_to(root).as_posix())
    return candidates


def compute_merge_entries(root: Path):
    """Liste (rel_path, priority_label) fuer Dateien, die im Ziel UND im Template existieren und sich
    unterscheiden. Leer, wenn kein Template-Remote verfuegbar ist (dann nichts zu vergleichen)."""
    remote, ref = _template_ref(root)
    if not ref:
        return []
    entries = []
    for rel in find_merge_candidates(root):
        res = run_git(root, ["show", f"{ref}:{rel}"])
        if res.returncode != 0:
            continue  # nicht im Template vorhanden -> projektspezifisch, kein Zusammenfuehren noetig
        template_content = res.stdout
        try:
            local_content = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if local_content != template_content:
            entries.append((rel, priority_label(rel)))
    return entries


# ---------------------------------------------------------------------------
# Orchestrator-Name: Erkennung + Ersetzung
# ---------------------------------------------------------------------------

ORCH_PATTERNS = [
    re.compile(r"Orchestrator\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})"),
    re.compile(r"([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})\s+ist\s+der\s+Orchestrator"),
    re.compile(r"Ich\s+bin\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})"),
]


def count_occurrences(root: Path, name: str) -> int:
    pattern = re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(name) + r"(?![\wÄÖÜäöüß])")
    total = 0
    for fp, _rel in _iter_text_files_for_rename(root):
        content = _read_text_or_none(fp)
        if content is None:
            continue
        total += len(pattern.findall(content))
    return total


def detect_orchestrator_names(root: Path, ai_dirs, moves):
    """Kandidaten fuer den bisherigen Orchestrator-Rufnamen, je Kandidat Trefferzahl im ganzen Repo,
    absteigend sortiert. Ersetzt NIE ungefragt."""
    names = {}
    for d in ai_dirs:
        n = d.name
        names.setdefault(n[:1].upper() + n[1:], None)

    text_sources = []
    for rel in ("CLAUDE.md", "AGENTS.md"):
        fp = root / rel
        if fp.is_file():
            try:
                text_sources.append(fp.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    for src, dest, _note in moves:
        if dest.name == "board.md":
            try:
                text_sources.append(src.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    for text in text_sources:
        for pat in ORCH_PATTERNS:
            for m in pat.finditer(text):
                names.setdefault(m.group(1), None)

    result = []
    for name in names:
        if len(name) < 2:
            continue
        cnt = count_occurrences(root, name)
        if cnt > 0:
            result.append((name, cnt))
    result.sort(key=lambda x: (-x[1], x[0]))
    return result


def _rename_variants(alt: str, neu: str):
    """3 Varianten case-sensitiv: Fable->Neu, fable->neu, FABLE->NEU (Duplikate entfernt, falls alt/neu
    bereits eine bestimmte Schreibweise haben)."""
    pairs = [(alt, neu), (alt.lower(), neu.lower()), (alt.upper(), neu.upper())]
    seen = {}
    for a, n in pairs:
        if a not in seen:
            seen[a] = n
    return list(seen.items())


# Beim projektweiten Ersetzen uebersprungene Verzeichnisse: fremder bzw. erzeugter Code, der den Rufnamen
# des Orchestrators nie meint - wuerde man dort schreiben, veraendert die Migration Abhaengigkeiten und
# Build-Ergebnisse. .claude/ bleibt bewusst drin (Agenten-/Skill-Dateien nennen den Namen).
RENAME_SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "out", "target", "vendor", "coverage",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".tox", ".gradle", ".idea",
}


def _read_text_or_none(fp: Path):
    """Dateiinhalt als Text - None bei Binaerdatei (NUL-Byte), kaputtem UTF-8 oder Lesefehler. Gelesen wird
    ueber Bytes, damit Zeilenenden (CRLF) und ein BOM unveraendert erhalten bleiben."""
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


def _iter_text_files_for_rename(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in RENAME_SKIP_DIR_NAMES]
        for fname in filenames:
            fp = Path(dirpath) / fname
            rel = fp.relative_to(root).as_posix()
            if rel == "CONFIG.md":
                continue
            if rel.startswith(".claude/scripts/") and rel.endswith(".py"):
                continue
            yield fp, rel


def rename_orchestrator(root: Path, alt: str, neu: str):
    """Ersetzt ALT durch NEU (3 Schreibvarianten, Wortgrenzen) in allen Textdateien ausser CONFIG.md,
    .claude/scripts/*.py und den Ordnern aus RENAME_SKIP_DIR_NAMES. Gibt (per_file: [(rel, anzahl)], total,
    fehler: [rel]) zurueck. Geschrieben wird ueber Bytes - Zeilenenden und BOM bleiben, wie sie waren."""
    if alt == neu:
        return [], 0, []
    variants = _rename_variants(alt, neu)
    patterns = [
        (re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(a) + r"(?![\wÄÖÜäöüß])"), n)
        for a, n in variants
    ]
    per_file = []
    fehler = []
    total = 0
    for fp, rel in _iter_text_files_for_rename(root):
        content = _read_text_or_none(fp)
        if content is None:
            continue
        new_content = content
        count_here = 0
        for pat, n in patterns:
            new_content, k = pat.subn(n, new_content)
            count_here += k
        if count_here and new_content != content:
            try:
                fp.write_bytes(new_content.encode("utf-8"))
            except OSError:
                fehler.append(rel)
                continue
            per_file.append((rel, count_here))
            total += count_here
    return per_file, total, fehler


def find_leftover_alt_dirs(root: Path, alt: str):
    """Ordner, die noch exakt wie ALT heissen (case-insensitiv) - werden hier nur gemeldet, nicht
    verschoben (das erledigt die Struktur-Migration)."""
    found = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for d in dirnames:
            if d.lower() == alt.lower():
                found.append((Path(dirpath) / d).relative_to(root).as_posix())
    return sorted(found)


# ---------------------------------------------------------------------------
# Git-Grundlagen + Modul-Wiederverwendung (template-update.py / new-project.py aus dem Ziel)
# ---------------------------------------------------------------------------


def run_git(root: Path, args, timeout=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", str(root)] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=timeout,
    )


def _load_module(root: Path, rel: str, mod_name: str):
    path = root / rel
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        return None
    return mod


def _template_ref(root: Path):
    """(remote, 'remote/branch') aus .claude/template.json - oder (None, None), wenn kein Remote 'template'
    existiert bzw. template-update.py im Ziel fehlt."""
    tu = _load_module(root, ".claude/scripts/template-update.py", "_template_update_mp")
    if tu is None:
        return None, None
    cfg, _path = tu.load_template_json(root)
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    if remote not in remotes:
        return None, None
    return remote, f"{remote}/{branch}"


def _config_orchestrator_values(root: Path):
    """(orchestrator, alter_orchestrator_name) aus CONFIG.md, ueber den new-project.py-Parser des Ziels.
    (None, None), wenn CONFIG.md/new-project.py fehlen."""
    cfg_path = root / "CONFIG.md"
    if not cfg_path.exists():
        return None, None
    np = _load_module(root, ".claude/scripts/new-project.py", "_new_project_mp")
    if np is None:
        return None, None
    try:
        text = cfg_path.read_text(encoding="utf-8-sig")
    except OSError:
        text = ""
    cfg = np.parse_config(text)
    return cfg.get("orchestrator"), cfg.get("alter_orchestrator_name")


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _check_root(root: Path) -> int:
    if not (root / "AGENTS.md").exists():
        print(
            f"Fehler: {root} sieht nicht nach einem Projekt aus diesem Template aus (AGENTS.md fehlt). "
            "Aufruf im Projekt-Root pruefen (bzw. CLAUDE_PROJECT_DIR).",
            file=sys.stderr,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------


def cmd_plan(root: Path, forced_alt=None, forced_neu=None) -> int:
    ai_dirs, moves, _conflicts, sub_md = build_plan(root)
    merge_entries = compute_merge_entries(root)
    if forced_alt and forced_neu:
        orch = [(forced_alt, count_occurrences(root, forced_alt))]
    else:
        orch = detect_orchestrator_names(root, ai_dirs, moves)
    moved_set = {m[0] for m in moves}
    empty_dirs = compute_empty_dirs(root, ai_dirs, moved_set)

    if not moves and not merge_entries and not orch:
        print("migrate-project.py --plan\n\nNichts zu tun.")
        return 0

    lines = ["migrate-project.py --plan", ""]

    lines.append("Verschieben:")
    if moves:
        for src, dest, note in moves[:20]:
            note_txt = f"  ({note})" if note else ""
            lines.append(f"  {src.relative_to(root).as_posix()}  ->  {dest.relative_to(root).as_posix()}{note_txt}")
        if len(moves) > 20:
            lines.append(f"  ... und {len(moves) - 20} weitere")
    else:
        lines.append("  (keine)")

    lines.append("")
    lines.append("Zusammenfuehren (Inhalt, macht der Assistent):")
    if merge_entries:
        _remote, ref = _template_ref(root)
        for rel, label in merge_entries[:15]:
            lines.append(f"  {rel}  [{label}]  git show {ref}:{rel}")
        if len(merge_entries) > 15:
            lines.append(f"  ... und {len(merge_entries) - 15} weitere")
        lines.append("")
        lines.append("Prioritaetsregeln:")
        lines.extend("  " + l for l in PRIORITY_RULES.splitlines())
    else:
        lines.append("  (keine, oder Template-Remote nicht verfuegbar - siehe .claude/template.json)")

    lines.append("")
    lines.append("Orchestrator-Name:")
    if orch:
        for name, cnt in orch[:10]:
            lines.append(f"  {name} ({cnt} Fundstellen)")
    else:
        lines.append("  (keine Kandidaten erkannt)")

    if sub_md:
        lines.append("")
        lines.append("Markdown in Unterordnern (NICHT automatisch verschoben - Struktur ist "
                     "projektspezifisch, bitte selbst zuordnen):")
        for f in sub_md[:20]:
            lines.append(f"  {f.relative_to(root).as_posix()}")
        if len(sub_md) > 20:
            lines.append(f"  ... und {len(sub_md) - 20} weitere")

    if empty_dirs:
        lines.append("")
        lines.append("Leer nach Migration (manuell pruefen und loeschen):")
        for d in empty_dirs:
            lines.append(f"  {d}")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------


def cmd_status(root: Path) -> int:
    ai_dirs, moves, conflicts, sub_md = build_plan(root)
    merge_entries = compute_merge_entries(root)
    orch = detect_orchestrator_names(root, ai_dirs, moves)

    lines = ["migrate-project.py --status", ""]
    lines.append(f"KI-Arbeitsordner (alt) gefunden: {len(ai_dirs)}")
    for d in ai_dirs:
        lines.append(f"  {d.relative_to(root).as_posix()}")
    lines.append(f"docs/ai/ vorhanden: {'ja' if (root / 'docs' / 'ai').is_dir() else 'nein'}")
    lines.append(f"Verschiebungen ausstehend: {len(moves)}")
    lines.append(f"Konflikte (mehrere Kandidaten je Zieldatei): {len(conflicts)}")
    lines.append(f"Zusammenfuehren ausstehend: {len(merge_entries)}")
    lines.append(f"Markdown in Unterordnern (manuell zuzuordnen): {len(sub_md)}")
    if orch:
        lines.append("Orchestrator-Kandidaten: " + ", ".join(f"{n}({c})" for n, c in orch[:5]))
    else:
        lines.append("Orchestrator-Kandidaten: (keine)")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------


def _git_mv(root: Path, rel_src: str, rel_dest: str) -> str:
    """"git" = per 'git mv' bewegt, "shutil" = Rueckfall (Datei nicht getrackt), "fehler" = gar nicht bewegt.
    Ein vorhandenes Ziel wird nie ueberschrieben - der Aufrufer sucht vorher einen freien Namen."""
    dest_path = root / rel_dest
    if dest_path.exists():
        return "fehler"
    res = run_git(root, ["mv", "--", rel_src, rel_dest])
    if res.returncode == 0:
        return "git"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(root / rel_src), str(dest_path))
    except OSError:
        return "fehler"
    run_git(root, ["add", "--", rel_dest])
    return "shutil"


def _free_alt_dest(dest: Path) -> Path:
    """Freien Namen fuer eine Altfassung neben dest suchen: name.alt.md, name.alt2.md, ... Ohne das wuerde
    die dritte Quelle mit gleichem Namen die zweite ueberschreiben (stiller Datenverlust)."""
    for i in range(1, 100):
        suffix = ".alt" if i == 1 else f".alt{i}"
        candidate = dest.with_name(dest.stem + suffix + dest.suffix)
        if not candidate.exists():
            return candidate
    return dest.with_name(dest.stem + ".alt99" + dest.suffix)


def _mv_note(status: str) -> str:
    if status == "shutil":
        return "  [shutil.move Rueckfall]"
    if status == "fehler":
        return "  [FEHLER: nicht verschoben, Quelle liegt unveraendert an ihrem Platz]"
    return ""


def execute_move(root: Path, src: Path, dest: Path, note) -> str:
    rel_src = src.relative_to(root).as_posix()
    if dest.exists():
        try:
            same = dest.read_bytes() == src.read_bytes()
        except OSError:
            same = False
        if same:
            res = run_git(root, ["rm", "-f", "--", rel_src])
            if res.returncode != 0:
                try:
                    src.unlink()
                except OSError:
                    pass
            rel_dest = dest.relative_to(root).as_posix()
            return f"  {rel_src}  ==  {rel_dest}  (inhaltsgleich, Altdatei geloescht)"
        alt_dest = _free_alt_dest(dest)
        rel_alt = alt_dest.relative_to(root).as_posix()
        status = _git_mv(root, rel_src, rel_alt)
        return (
            f"  {rel_src}  ->  {rel_alt}  (Ziel existiert bereits und unterscheidet sich - zusammenfuehren)"
            + _mv_note(status)
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    rel_dest = dest.relative_to(root).as_posix()
    status = _git_mv(root, rel_src, rel_dest)
    note_txt = f"  [{note}]" if note else ""
    return f"  {rel_src}  ->  {rel_dest}{note_txt}" + _mv_note(status)


def check_clean_worktree(root: Path) -> int:
    """Vorbedingung fuer jeden schreibenden Lauf (--apply wie --rename-orchestrator): Git-Repo und sauberer
    Arbeitsbaum - beides schreibt breit ins Repo und ist sonst nicht rueckgaengig zu machen. 0 = ok."""
    res_git = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if res_git.returncode != 0 or res_git.stdout.strip() != "true":
        print("Fehler: kein Git-Repo - Migration erfordert Git (Historie/Rueckgaengigmachen).", file=sys.stderr)
        return 2
    res_status = run_git(root, ["status", "--porcelain"])
    if res_status.stdout.strip():
        print(
            "Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, damit die Migration rueckgaengig "
            "gemacht werden kann.",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_apply(root: Path, forced_alt=None, forced_neu=None) -> int:
    rc = check_clean_worktree(root)
    if rc != 0:
        return rc

    ai_dirs, moves, _conflicts, _sub = build_plan(root)

    lines = ["migrate-project.py --apply", ""]
    lines.append("Verschoben:")
    if moves:
        (root / "docs" / "ai").mkdir(parents=True, exist_ok=True)
        for src, dest, note in moves:
            lines.append(execute_move(root, src, dest, note))
    else:
        lines.append("  (keine - nichts zu verschieben)")

    empty_dirs = compute_empty_dirs(root, ai_dirs, moved_set=None)
    if empty_dirs:
        lines.append("")
        lines.append("Leer nach Migration (manuell pruefen und loeschen):")
        for d in empty_dirs:
            lines.append(f"  {d}")

    alt, neu = forced_alt, forced_neu
    if not alt:
        cfg_orch, cfg_alt = _config_orchestrator_values(root)
        if cfg_alt:
            alt = cfg_alt
            # Kein fester Rueckfallname: ohne CONFIG.md § Orchestrator wuerde sonst ein fremder Name ins
            # ganze Repo geschrieben.
            neu = neu or cfg_orch

    lines.append("")
    if alt and neu:
        per_file, total, fehler = rename_orchestrator(root, alt, neu)
        lines.append(f"Orchestrator-Name: '{alt}' -> '{neu}' ({total} Ersetzungen in {len(per_file)} Dateien)")
        for rel, cnt in per_file[:20]:
            lines.append(f"  {rel}: {cnt}")
        if len(per_file) > 20:
            lines.append(f"  ... und {len(per_file) - 20} weitere Dateien")
        for rel in fehler:
            lines.append(f"  FEHLER, nicht geschrieben (schreibgeschuetzt?): {rel}")
        leftover = find_leftover_alt_dirs(root, alt)
        if leftover:
            lines.append("  Achtung: Ordner heissen noch wie der alte Name (manuell klaeren):")
            for d in leftover:
                lines.append(f"    {d}")
    elif alt:
        lines.append(f"Orchestrator-Name: alter Name '{alt}' bekannt, aber kein neuer - CONFIG.md § "
                      "\"Orchestrator\" ist leer. Keine Ersetzung ausgefuehrt, bei Bedarf einzeln mit "
                      "--rename-orchestrator ALT=NEU.")
    else:
        lines.append("Orchestrator-Name: kein Name uebergeben und keiner in CONFIG.md § \"Alter "
                      "Orchestrator-Name\" gesetzt - keine Ersetzung ausgefuehrt.")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate-project.py",
        description="Bestehendes Repo (Weg 2) auf die Template-Struktur migrieren: KI-Arbeitsordner "
        "erkennen/verschieben, Zusammenfuehr-Kandidaten melden, Orchestrator-Rufnamen ersetzen.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="Migrationsplan zeigen, nichts schreiben (Default)")
    group.add_argument("--apply", action="store_true", help="Plan ausfuehren")
    group.add_argument("--status", action="store_true", help="Kurzuebersicht Template-Konformitaet")
    parser.add_argument(
        "--rename-orchestrator", metavar="ALT=NEU", default=None,
        help="Orchestrator-Rufnamen ersetzen; mit --plan kombiniert nur anzeigen, sonst sofort ausfuehren",
    )
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = _find_root()
    rc = _check_root(root)
    if rc != 0:
        return rc

    alt, neu = None, None
    if args.rename_orchestrator:
        if "=" not in args.rename_orchestrator:
            print(
                f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - erwartet "
                "ALT=NEU.",
                file=sys.stderr,
            )
            return 2
        alt, neu = (p.strip() for p in args.rename_orchestrator.split("=", 1))
        if not alt or not neu:
            print(
                f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - ALT und NEU "
                "duerfen nicht leer sein.",
                file=sys.stderr,
            )
            return 2

    if args.status:
        return cmd_status(root)
    if args.apply:
        return cmd_apply(root, alt, neu)
    if args.rename_orchestrator and not args.plan:
        # Nur die Namensersetzung, ohne Struktur-Migration. Schreibt in jede Textdatei des Repos und braucht
        # deshalb dieselbe Vorbedingung wie --apply.
        rc = check_clean_worktree(root)
        if rc != 0:
            return rc
        if alt == neu:
            print(f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - ALT und NEU "
                  "sind identisch.", file=sys.stderr)
            return 2
        per_file, total, fehler = rename_orchestrator(root, alt, neu)
        lines = [
            f"migrate-project.py --rename-orchestrator {args.rename_orchestrator}", "",
            f"Orchestrator-Name: '{alt}' -> '{neu}' ({total} Ersetzungen in {len(per_file)} Dateien)",
        ]
        for rel, cnt in per_file[:30]:
            lines.append(f"  {rel}: {cnt}")
        if len(per_file) > 30:
            lines.append(f"  ... und {len(per_file) - 30} weitere Dateien")
        for rel in fehler:
            lines.append(f"  FEHLER, nicht geschrieben (schreibgeschuetzt?): {rel}")
        leftover = find_leftover_alt_dirs(root, alt)
        if leftover:
            lines.append("Achtung: Ordner heissen noch wie der alte Name (manuell klaeren):")
            for d in leftover:
                lines.append(f"  {d}")
        print("\n".join(lines))
        return 0

    return cmd_plan(root, alt, neu)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"migrate-project: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
