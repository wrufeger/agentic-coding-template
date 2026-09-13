#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Haelt die Testprojekte-Tabelle in .templatedev/README.md (zwischen den Markern
#        "<!-- testprojekte:start -->"/"<!-- testprojekte:end -->") gegen den echten Git-Stand der dort
#        eingetragenen Projekte aktuell. Die Commits dieser Projekte liegen bislang nur lokal - der
#        eingetragene Hash ist die einzige belastbare Referenz auf einen Stand, siehe README.md. Reine
#        Python-Stdlib, kein Paket noetig. Nur fuer die Template-Entwicklung selbst (.templatedev/), gehoert
#        nicht zum Lieferumfang eines abgeleiteten Projekts.
#
# Aufruf:
#   python .templatedev/testprojekte.py [--check] [--readme <pfad>]
#       (Default) Vergleicht je Projekt den eingetragenen Commit-Hash gegen den tatsaechlichen HEAD-Commit
#       des Pfads. Schreibt NICHTS. Bei Gleichstand eine Zeile "unveraendert"; bei Abweichung alter/neuer
#       Hash, Anzahl dazwischenliegender Commits (git rev-list --count) und deren Betreffzeilen (hoechstens
#       10, danach "... und N weitere"). Fehlt der Pfad oder ist er kein Git-Repo, wird das als Problem
#       gemeldet statt abzustuerzen. Zusaetzlich je Projekt eine Zeile "Stand" (Arbeitsbaum sauber/geaendert,
#       Push-Stand - dieselbe Logik wie bei --update).
#   python .templatedev/testprojekte.py --update [--readme <pfad>]
#       Gibt dieselbe Uebersicht wie --check aus UND schreibt die Tabelle zwischen den Markern neu: Spalten
#       "Letzter geprueften Commit" (Hash plus Datum) und "Stand" werden aus dem aktuellen Git-Stand gesetzt,
#       die Spalten Projekt/Pfad/Weg bleiben unangetastet (die werden von Hand gepflegt). Schreibt atomar
#       (Temp-Datei im selben Verzeichnis, dann os.replace, Temp-Datei im Fehlerfall aufgeraeumt) und erhaelt
#       das Zeilenende der Datei.
#   --readme <pfad>: abweichender Pfad zur README (Default: .templatedev/README.md im Repo-Root, Root aus
#       CLAUDE_PROJECT_DIR oder aus dem Pfad dieses Scripts). Praktisch zum Testen gegen eine Kopie.
#
# Wichtig: Das Script liest fremde Repos nur (rev-parse, log, status, rev-list, cat-file -e) - es fuehrt dort
#   NIE schreibende oder netzwerkfaehige Git-Befehle aus (kein fetch, kein pull, kein checkout).
#
# "Ungepuscht": hat die Projekt-Branch einen Upstream, zaehlt "<upstream>..HEAD" die noch nicht gepushten
#   Commits. Ohne Upstream (der heutige Normalfall bei den Testprojekten) ist das kein Fehler - gemeldet wird
#   "nur lokal", zusaetzlich die Anzahl der Commits, die auf keinem bekannten Remote-Tracking-Branch liegen
#   ("HEAD --not --remotes"; ohne jeden Remote entspricht das schlicht allen lokalen Commits).
#
# Exit-Codes: 0 = alles gleich (--check) bzw. erfolgreich geschrieben (--update), 1 = mindestens ein Projekt
#   weicht ab (nur bei --check), 2 = Vorbedingungsfehler (README nicht lesbar, Marker fehlen, Tabelle
#   unlesbar, unbekannte Argumente). main() laeuft komplett in try/except - kein Traceback nach aussen.

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

MARKER_START = "<!-- testprojekte:start -->"
MARKER_END = "<!-- testprojekte:end -->"
DEFAULT_README_REL = ".templatedev/README.md"
GIT_TIMEOUT = 20
COLUMNS = ["Projekt", "Pfad", "Weg", "Letzter geprüfter Commit", "Stand"]
COMMIT_CELL_RE = re.compile(r"`([0-9a-fA-F]+)`(?:\s*\(([^)]*)\))?")
BETWEEN_LIMIT = 10


class TableError(Exception):
    """Marker/Tabelle in der README fehlen oder sind nicht eindeutig lesbar."""


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# README-Tabelle lesen
# ---------------------------------------------------------------------------


def _split_row(line: str):
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|")) or len(line) < 2:
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def _extract_backtick(cell: str) -> str:
    m = re.search(r"`([^`]+)`", cell)
    return m.group(1) if m else cell.strip()


def parse_readme(path: Path) -> dict:
    """Liest die README und gibt ein dict mit den fuer das Zurueckschreiben noetigen Rohdaten zurueck.
    Wirft TableError bei fehlenden Markern oder einer nicht eindeutig lesbaren Tabelle."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    trailing_newline = text.endswith(newline)
    lines = text.split(newline)
    if trailing_newline:
        lines = lines[:-1]

    start_candidates = [i for i, l in enumerate(lines) if l.strip() == MARKER_START]
    end_candidates = [i for i, l in enumerate(lines) if l.strip() == MARKER_END]
    if len(start_candidates) != 1 or len(end_candidates) != 1:
        raise TableError(
            f"Marker {MARKER_START} / {MARKER_END} fehlen oder sind nicht eindeutig (je genau einmal erwartet)."
        )
    start_idx, end_idx = start_candidates[0], end_candidates[0]
    if end_idx <= start_idx:
        raise TableError("Endmarker steht vor dem Startmarker.")

    block = lines[start_idx + 1 : end_idx]
    if len(block) < 3:
        raise TableError("Tabelle zwischen den Markern ist leer oder unvollstaendig.")

    header_cells = _split_row(block[0])
    sep_cells = _split_row(block[1])
    if header_cells is None or sep_cells is None:
        raise TableError("Kopf- oder Trennzeile der Tabelle nicht lesbar.")
    if header_cells != COLUMNS:
        raise TableError(f"Tabellenkopf weicht ab - erwartet {COLUMNS}, gefunden {header_cells}.")

    rows = []
    for raw_line in block[2:]:
        if not raw_line.strip():
            continue
        cells = _split_row(raw_line)
        if cells is None or len(cells) != len(COLUMNS):
            raise TableError(f"Tabellenzeile nicht lesbar: {raw_line!r}")
        rows.append(
            {
                "projekt": cells[0],
                "pfad_cell": cells[1],
                "pfad": _extract_backtick(cells[1]),
                "weg": cells[2],
                "commit_cell": cells[3],
                "stand_cell": cells[4],
            }
        )
    if not rows:
        raise TableError("Tabelle enthaelt keine Projektzeile.")

    return {
        "lines": lines,
        "newline": newline,
        "trailing_newline": trailing_newline,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "header": block[0],
        "sep": block[1],
        "rows": rows,
    }


def parse_commit_cell(cell: str):
    m = COMMIT_CELL_RE.search(cell)
    if not m:
        return None, None
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Git-Zugriff auf das Testprojekt - nur lesend
# ---------------------------------------------------------------------------


def _git(args, cwd: Path):
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )


def _is_git_repo(path: Path) -> bool:
    try:
        res = _git(["rev-parse", "--is-inside-work-tree"], path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0 and res.stdout.strip() == "true"


def _head_info(path: Path):
    """(hash, datum, betreff) des HEAD-Commits, oder None (leeres Repo/Fehler)."""
    try:
        res = _git(["log", "-1", "--date=short", "--format=%h\x1f%ad\x1f%s"], path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    parts = res.stdout.rstrip("\n").split("\x1f")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def _dirty_count(path: Path):
    try:
        res = _git(["status", "--porcelain"], path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return len([l for l in res.stdout.splitlines() if l.strip()])


def _upstream(path: Path):
    try:
        res = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def _rev_list_count(path: Path, extra_args):
    try:
        res = _git(["rev-list", "--count"] + extra_args, path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None


def _commit_exists(path: Path, rev: str) -> bool:
    try:
        res = _git(["cat-file", "-e", rev + "^{commit}"], path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def _log_subjects(path: Path, extra_args, limit: int):
    try:
        res = _git(["log", f"-n{limit}", "--format=%s"] + extra_args, path)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if res.returncode != 0:
        return []
    return res.stdout.splitlines()


def gather_status(pfad_str: str) -> dict:
    """Ermittelt den tatsaechlichen Git-Stand eines Testprojekt-Pfads. Keine schreibenden/netzwerkfaehigen
    Befehle (kein fetch/pull/checkout) - nur lesende Abfragen."""
    path = Path(pfad_str)
    status = {"path_exists": path.is_dir(), "is_repo": False}
    if not status["path_exists"]:
        return status
    if not _is_git_repo(path):
        return status
    status["is_repo"] = True
    status["head"] = _head_info(path)
    status["dirty"] = _dirty_count(path)
    upstream = _upstream(path)
    status["upstream"] = upstream
    if upstream:
        status["ahead"] = _rev_list_count(path, [f"{upstream}..HEAD"])
        status["local_unpushed"] = None
    else:
        status["ahead"] = None
        status["local_unpushed"] = _rev_list_count(path, ["HEAD", "--not", "--remotes"])
    return status


def _commit_word(n: int) -> str:
    return "Commit" if n == 1 else "Commits"


def compute_stand(status: dict) -> str:
    if not status.get("path_exists"):
        return "Pfad fehlt"
    if not status.get("is_repo"):
        return "kein Git-Repository"

    dirty = status.get("dirty")
    if dirty is None:
        parts = ["Arbeitsbaumstatus nicht ermittelbar"]
    elif dirty == 0:
        parts = ["Arbeitsbaum sauber"]
    elif dirty == 1:
        parts = ["1 Datei geaendert"]
    else:
        parts = [f"{dirty} Dateien geaendert"]

    if status.get("upstream"):
        ahead = status.get("ahead")
        if ahead:
            parts.append(f"{ahead} {_commit_word(ahead)} ungepusht")
    else:
        local = status.get("local_unpushed")
        if local:
            parts.append(f"nur lokal, {local} {_commit_word(local)} ungepusht")
        else:
            parts.append("nur lokal")
    return ", ".join(parts)


def format_commit_cell(status: dict) -> str:
    head = status.get("head")
    if not head:
        return "—"
    h, d, _s = head
    return f"`{h}` ({d})"


# ---------------------------------------------------------------------------
# Uebersicht je Projekt (gemeinsam fuer --check und --update)
# ---------------------------------------------------------------------------


def build_project_report(row: dict, status: dict):
    """Gibt (lines, issue) zurueck - lines ist die Textausgabe fuer dieses Projekt, issue ist True, wenn der
    verzeichnete Stand vom tatsaechlichen abweicht (fehlender Pfad/Repo zaehlt ebenfalls als Abweichung)."""
    lines = [f"{row['projekt']} (`{row['pfad']}`):"]

    if not status.get("path_exists"):
        lines.append("  Pfad fehlt")
        return lines, True
    if not status.get("is_repo"):
        lines.append("  kein Git-Repository")
        return lines, True

    head = status.get("head")
    if head is None:
        lines.append("  HEAD nicht ermittelbar (leeres Repo?)")
        return lines, True
    cur_hash, cur_date, _cur_subject = head

    recorded_hash, recorded_date = parse_commit_cell(row["commit_cell"])
    if recorded_hash and recorded_hash == cur_hash:
        lines.append(f"  unveraendert ({cur_hash}, {cur_date})")
        issue = False
    else:
        issue = True
        if recorded_hash:
            recorded_txt = f"{recorded_hash}" + (f" ({recorded_date})" if recorded_date else "")
        else:
            recorded_txt = "kein verzeichneter Commit"
        lines.append(f"  ABWEICHUNG: verzeichnet {recorded_txt} -> aktuell {cur_hash} ({cur_date})")

        path = Path(row["pfad"])
        if recorded_hash and _commit_exists(path, recorded_hash):
            count = _rev_list_count(path, [f"{recorded_hash}..{cur_hash}"])
            count_txt = count if count is not None else "unbekannt viele"
            lines.append(f"  {count_txt} Commit(s) dazwischen:")
            subjects = _log_subjects(path, [f"{recorded_hash}..{cur_hash}"], BETWEEN_LIMIT)
            for subj in subjects:
                lines.append(f"    - {subj}")
            if isinstance(count, int) and count > BETWEEN_LIMIT:
                lines.append(f"    ... und {count - BETWEEN_LIMIT} weitere")
        elif recorded_hash:
            lines.append("  verzeichneter Commit nicht mehr im Repo auffindbar (Rebase/Force-Push?)")

    lines.append(f"  Stand: {compute_stand(status)}")
    return lines, issue


# ---------------------------------------------------------------------------
# --check / --update
# ---------------------------------------------------------------------------


def cmd_check(readme_path: Path) -> int:
    table = parse_readme(readme_path)
    any_issue = False
    for row in table["rows"]:
        status = gather_status(row["pfad"])
        lines, issue = build_project_report(row, status)
        for l in lines:
            print(l)
        print()
        any_issue = any_issue or issue
    if any_issue:
        print("Zusammenfassung: mindestens ein Projekt weicht vom verzeichneten Stand ab.")
        return 1
    print("Zusammenfassung: alle Projekte unveraendert.")
    return 0


def _format_row(cells) -> str:
    return "| " + " | ".join(cells) + " |"


def _write_table(path: Path, table: dict, new_rows_cells) -> None:
    lines = list(table["lines"])
    new_block = [table["header"], table["sep"]] + [_format_row(c) for c in new_rows_cells]
    lines[table["start_idx"] + 1 : table["end_idx"]] = new_block
    newline = table["newline"]
    text = newline.join(lines) + (newline if table["trailing_newline"] else "")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = f.name
            f.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def cmd_update(readme_path: Path) -> int:
    table = parse_readme(readme_path)
    any_issue = False
    new_rows_cells = []
    for row in table["rows"]:
        status = gather_status(row["pfad"])
        lines, issue = build_project_report(row, status)
        for l in lines:
            print(l)
        print()
        any_issue = any_issue or issue
        new_rows_cells.append(
            [row["projekt"], row["pfad_cell"], row["weg"], format_commit_cell(status), compute_stand(status)]
        )

    _write_table(readme_path, table, new_rows_cells)
    hinweis = "Abweichungen gefunden" if any_issue else "keine Abweichungen"
    print(f"Zusammenfassung: {hinweis}, Tabelle in {readme_path} fortgeschrieben.")
    return 0


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    try:
        parser = argparse.ArgumentParser(
            description="Vergleicht/aktualisiert die Testprojekte-Tabelle in .templatedev/README.md gegen "
            "den echten Git-Stand der eingetragenen Projekte."
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--check", action="store_true", help="Nur vergleichen, nichts schreiben (Default).")
        group.add_argument("--update", action="store_true", help="Tabelle mit dem aktuellen Stand fortschreiben.")
        parser.add_argument(
            "--readme",
            help="Pfad zur README mit der Testprojekte-Tabelle (Default: .templatedev/README.md im Repo-Root).",
        )
        args = parser.parse_args(argv)

        readme_path = Path(args.readme) if args.readme else _find_root() / DEFAULT_README_REL
        if not readme_path.is_file():
            print(f"testprojekte.py: {readme_path} nicht lesbar.", file=sys.stderr)
            return 2

        try:
            if args.update:
                return cmd_update(readme_path)
            return cmd_check(readme_path)
        except TableError as exc:
            print(f"testprojekte.py: {exc}", file=sys.stderr)
            return 2
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return code if code == 0 else 2
    except Exception as exc:  # noqa: BLE001 - nie ein Traceback nach aussen
        print(f"testprojekte.py: Fehler - {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
