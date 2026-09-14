#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Bestandsaufnahme eines beliebigen Codebaums - Umfang und Struktur messen, ohne dass ein Sub-Agent
#        (z. B. `explorer`) tausende Dateien lesen muss. Nuetzlich beim Uebernehmen eines fremden Projekts
#        oder beim Nachruesten (`/apply-template`): Zahlen statt Vermutungen. Liefert Zeilen je Verzeichnis
#        und je Dateityp, trennt Code von Markdown/Konfiguration, zaehlt TODO/FIXME/HACK/XXX-Markierungen
#        und listet die groessten Einzeldateien. Allgemeine Weiterentwicklung von legacy-inventory.py
#        (Projekt "bandliste", dort auf eine feste alte PHP-Struktur zugeschnitten).
#
# Aufruf: python .claude/scripts/code-inventory.py [--root <pfad>] [--top <n>] [--json] [--alle]
#         --root  Zu vermessende Wurzel (Default: CLAUDE_PROJECT_DIR, sonst die Repo-Wurzel relativ zu
#                 dieser Datei - siehe _find_root(), gleiches Muster wie finish-setup.py)
#         --top   Anzahl Zeilen je Rangliste "Groesste Dateien" (Default: 25)
#         --json  Maschinenlesbare Ausgabe statt Texttabellen
#         --alle  Auch Abhaengigkeits-/Build-Ordner (EXCLUDE_DIRS) mitzaehlen UND die Gitignore-Pruefung
#                 abschalten - zaehlt wirklich alles ausser dem immer uebersprungenen ".git". Ohne --alle
#                 werden beide Ausschluesse getrennt ausgewiesen (Anzahl Dateien), aber nicht mitgezaehlt;
#                 ihr Inhalt wird dafuer nur ueberflogen (Dateien zaehlen), nicht gelesen (Zeilen/Marker) -
#                 sonst waere ein einzelnes node_modules/ schon zu teuer.
#
# Ausschluesse (Verzeichnisname, an beliebiger Tiefe, ohne Beachtung der Gross-/Kleinschreibung):
#   node_modules, .git (immer, unabhaengig von --alle), dist, build, .nuxt, .output, target, bin, obj,
#   __pycache__, .venv, venv, coverage, .next, vendor
# Gitignore: in einem Git-Repository wird zusaetzlich einmalig `git ls-files --others --ignored
#   --exclude-standard --directory` abgefragt (ein Aufruf, keine Datei einzeln geprueft) und alles, was Git
#   als ignoriert meldet, standardmaessig ausgeklammert und getrennt ausgewiesen. Kein Git-Repo -> dieser
#   Schritt entfaellt geraeuschlos (kein Fehler, kein Eintrag).
#
# Dateitypen:
#   CODE       .php .js .ts .tsx .vue .java .kt .go .cs .rb .rs .swift .scala .dart .mjs .cjs .css .scss
#              .less .tpl .html .htm .inc .sql .py .pl .sh
#   MARKDOWN   .md                                  (Doku-Zeilen sind keine Codezeilen - getrennt ausgewiesen)
#   KONFIG     .yaml .yml .json .toml .ini .xml
#   alles andere zaehlt als Datei, aber nicht als Zeilen ("binaer_oder_sonstige").
#
# Ausgabe: Texttabellen (Default) - Gesamtzahlen (Code/Markdown/Konfiguration getrennt), Ausschluss-/
#   Gitignore-Zahlen, Verzeichnisse nach Zeilen, Dateitypen, TODO/FIXME/HACK/XXX (Anzahl Dateien + Top 10),
#   groesste Dateien. --json liefert dasselbe als ein JSON-Objekt. Exit 0, auch wenn leer; Exit 1, wenn
#   --root nicht existiert. main() laeuft komplett in try/except - kein Traceback nach aussen.

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

CODE_EXT = {
    ".php", ".js", ".ts", ".tsx", ".vue", ".java", ".kt", ".go", ".cs", ".rb", ".rs", ".swift",
    ".scala", ".dart", ".mjs", ".cjs", ".css", ".scss", ".less", ".tpl", ".html", ".htm", ".inc",
    ".sql", ".py", ".pl", ".sh",
}
MARKDOWN_EXT = {".md"}
CONFIG_EXT = {".yaml", ".yml", ".json", ".toml", ".ini", ".xml"}
ALLE_EXT = CODE_EXT | MARKDOWN_EXT | CONFIG_EXT

# Verzeichnisnamen, die standardmaessig uebersprungen werden (Punkt 3 im Auftrag) - ".git" kommt unten
# separat und immer dazu, unabhaengig von --alle.
EXCLUDE_DIRS = {
    "node_modules", "dist", "build", ".nuxt", ".output", "target", "bin", "obj", "__pycache__",
    ".venv", "venv", "coverage", ".next", "vendor",
}
HARD_SKIP = {".git"}

MARKER_RE = re.compile(rb"\b(?:TODO|FIXME|HACK|XXX)\b")
TODO_TOP_N = 10


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def analyse(path: str):
    """Ein Lesevorgang je Datei: liefert (zeilen, marker_treffer) - Zeilenzaehlung und TODO/FIXME/HACK/XXX
    teilen sich den Puffer, damit keine Datei zweimal geoeffnet wird."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return 0, 0
    return data.count(b"\n") + 1, len(MARKER_RE.findall(data))


def count_files_only(path: str) -> int:
    """Zaehlt Dateien unterhalb von path, ohne eine einzige zu oeffnen - fuer Ausschluss-/Gitignore-Ordner,
    die beliebig gross sein koennen (node_modules, old-project, ...)."""
    n = 0
    for _dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in HARD_SKIP]
        n += len(filenames)
    return n


def git_ignored(root: Path):
    """Ein einziger Git-Aufruf statt einer Pruefung je Datei. Gibt (is_git, ignorierte_ordner,
    ignorierte_dateien) zurueck - Pfade posix-relativ zu root, Ordner ohne Endschraegstrich. Kein
    Git-Repo/Fehler/Timeout -> (False, set(), set()), geraeuschlos."""
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, set(), set()
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return False, set(), set()
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard",
             "--directory", "-z"],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True, set(), set()
    if res.returncode != 0:
        return True, set(), set()
    dirs, files = set(), set()
    for entry in res.stdout.decode("utf-8", "replace").split("\0"):
        if not entry:
            continue
        if entry.endswith("/"):
            dirs.add(entry[:-1])
        else:
            files.add(entry)
    return True, dirs, files


def _posix(rel: str) -> str:
    return rel.replace(os.sep, "/")


def scan(root: Path, alle: bool):
    is_git, ignored_dirs, ignored_files = (False, set(), set()) if alle else git_ignored(root)

    pro_dir = defaultdict(lambda: {"dateien": 0, "zeilen": 0})
    pro_ext = defaultdict(lambda: {"dateien": 0, "zeilen": 0})
    dateien, binaer = 0, 0
    codezeilen, mdzeilen, configzeilen = 0, 0, 0
    ausgeschlossen_ordner, gitignoriert_ordner = set(), set()
    ausgeschlossen_dateien, gitignoriert_dateien = 0, 0
    groesste = []
    todo_je_datei = {}

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        rel_dir = "." if dirpath == str(root) else _posix(os.path.relpath(dirpath, root))
        behalten = []
        for d in dirnames:
            if d in HARD_SKIP:
                continue
            rel_sub = d if rel_dir == "." else f"{rel_dir}/{d}"
            if not alle and d.lower() in EXCLUDE_DIRS:
                ausgeschlossen_ordner.add(rel_sub)
                ausgeschlossen_dateien += count_files_only(os.path.join(dirpath, d))
                continue
            if not alle and is_git and rel_sub in ignored_dirs:
                gitignoriert_ordner.add(rel_sub)
                gitignoriert_dateien += count_files_only(os.path.join(dirpath, d))
                continue
            behalten.append(d)
        dirnames[:] = behalten

        top = "." if rel_dir == "." else rel_dir.split("/")[0]
        for fn in filenames:
            rel_file = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if not alle and is_git and rel_file in ignored_files:
                gitignoriert_dateien += 1
                continue
            full = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            dateien += 1
            if ext not in ALLE_EXT:
                binaer += 1
                continue
            n, marker = analyse(full)
            if ext in CODE_EXT:
                codezeilen += n
            elif ext in MARKDOWN_EXT:
                mdzeilen += n
            else:
                configzeilen += n
            pro_ext[ext]["dateien"] += 1
            pro_ext[ext]["zeilen"] += n
            d = pro_dir[top]
            d["dateien"] += 1
            d["zeilen"] += n
            groesste.append((n, rel_file))
            if marker:
                todo_je_datei[rel_file] = marker

    return {
        "root": str(root),
        "dateien_gesamt": dateien,
        "davon_binaer_oder_sonstige": binaer,
        "codezeilen": codezeilen,
        "markdownzeilen": mdzeilen,
        "konfigzeilen": configzeilen,
        "ausgeschlossen": {
            "ordner_muster": sorted(EXCLUDE_DIRS),
            "gefunden": sorted(ausgeschlossen_ordner),
            "dateien": ausgeschlossen_dateien,
        },
        "gitignoriert": {
            "aktiv": is_git,
            "ordner": sorted(gitignoriert_ordner),
            "dateien": gitignoriert_dateien,
        },
        "verzeichnisse": sorted(pro_dir.items(), key=lambda kv: -kv[1]["zeilen"]),
        "dateitypen": sorted(pro_ext.items(), key=lambda kv: -kv[1]["zeilen"]),
        "groesste": groesste,
        "todo_marker": {
            "dateien_mit_marker": len(todo_je_datei),
            "top": sorted(todo_je_datei.items(), key=lambda kv: (-kv[1], kv[0]))[:TODO_TOP_N],
        },
    }


def main() -> int:
    try:
        ap = argparse.ArgumentParser(description="Bestandsaufnahme eines Codebaums (Zeilen, Typen, TODOs).")
        ap.add_argument("--root", default=None)
        ap.add_argument("--top", type=int, default=25)
        ap.add_argument("--json", action="store_true")
        ap.add_argument("--alle", action="store_true")
        a = ap.parse_args()
        root = Path(a.root).resolve() if a.root else _find_root()
        if not root.is_dir():
            print(f"Nicht gefunden: {root}", file=sys.stderr)
            return 1

        ergebnis = scan(root, a.alle)
        ergebnis["groesste"] = sorted(ergebnis["groesste"], reverse=True)[: a.top]

        if a.json:
            print(json.dumps(ergebnis, indent=2, ensure_ascii=False))
            return 0

        def zt(n):
            return f"{n:,}".replace(",", ".")

        print(f"Wurzel: {ergebnis['root']}")
        print(f"Dateien im Umfang: {zt(ergebnis['dateien_gesamt'])}  "
              f"(davon {zt(ergebnis['davon_binaer_oder_sonstige'])} binaer/sonstige)")
        print(f"Codezeilen: {zt(ergebnis['codezeilen'])}   "
              f"Markdown-Zeilen: {zt(ergebnis['markdownzeilen'])}   "
              f"Konfig-Zeilen: {zt(ergebnis['konfigzeilen'])}")

        aus = ergebnis["ausgeschlossen"]
        if not a.alle:
            if aus["gefunden"]:
                print(f"Ausgeschlossen (Ordnername): {zt(aus['dateien'])} Dateien in "
                      f"{', '.join(aus['gefunden'])}")
            gi = ergebnis["gitignoriert"]
            if gi["aktiv"] and gi["ordner"]:
                print(f"Gitignoriert: {zt(gi['dateien'])} Dateien in {', '.join(gi['ordner'])}")
            elif not gi["aktiv"]:
                print("Gitignoriert: kein Git-Repository erkannt - Pruefung uebersprungen.")

        print(f"\n{'Verzeichnis':<28}{'Dateien':>9}{'Zeilen':>12}")
        print("-" * 49)
        for k, v in ergebnis["verzeichnisse"][: a.top]:
            print(f"{k[:27]:<28}{v['dateien']:>9}{zt(v['zeilen']):>12}")

        print(f"\n{'Typ':<10}{'Dateien':>9}{'Zeilen':>12}")
        print("-" * 31)
        for k, v in ergebnis["dateitypen"]:
            print(f"{k:<10}{v['dateien']:>9}{zt(v['zeilen']):>12}")

        tm = ergebnis["todo_marker"]
        print(f"\nTODO/FIXME/HACK/XXX: {zt(tm['dateien_mit_marker'])} Dateien mit Treffern")
        for count, p in tm["top"]:
            print(f"  {count:>4}  {p}")

        print("\nGroesste Dateien (Zeilen):")
        for n, p in ergebnis["groesste"]:
            print(f"  {zt(n):>9}  {p}")
        return 0
    except Exception as exc:  # noqa: BLE001 - nie ein Traceback nach aussen
        print(f"code-inventory.py: Fehler - {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
