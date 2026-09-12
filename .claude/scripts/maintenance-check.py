#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Faelligkeit der wiederkehrenden Wartung (`.claude/maintenance/status.json`) pruefen und pflegen -
#        Grundlage fuer den SessionStart-Hook (meldet nur, wenn tatsaechlich etwas faellig ist) und fuer den
#        Skill `/run-maintenance` (Default ohne Argument = nur faellige Aufgaben). Siehe
#        `.claude/maintenance/README.md`, `.claude/skills/run-maintenance/SKILL.md`,
#        `.claude/agents/maintenance-orchestrator.md`. Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf:
#   python .claude/scripts/maintenance-check.py --check [--quiet]
#       (Default, auch ohne Argument) Prueft status.json auf faellige Aufgaben. Faellig = `naechster_lauf`
#       gesetzt und <= heute, ODER `intervall_tage` gesetzt und `letzter_lauf` null (noch nie gelaufen).
#       Fehlt status.json/der Wartungsordner, ist die Datei kaputt, oder ist nichts faellig: KEINE Ausgabe,
#       Exit 0 (Wartung ist dann entweder abgeschaltet oder gerade nichts zu tun - beides kein Fehler).
#       Sonst kurzer Block (max. 8 Zeilen) mit den faelligen Aufgaben, weiterhin Exit 0 - so kann ein
#       SessionStart-Hook die Ausgabe als Kontext einfuegen, ohne je einen Fehler zu erzeugen. --quiet ist
#       fuer den Hook-Aufruf aus settings.json vorgesehen; das Verhalten ist mit/ohne --quiet identisch, weil
#       schon --check allein in jedem Nicht-faellig-Fall still bleibt.
#   python .claude/scripts/maintenance-check.py --list
#       Alle Aufgaben mit Intervall, letztem/naechstem Lauf und Status (faellig / in n Tagen /
#       ereignisgesteuert / nie gelaufen).
#   python .claude/scripts/maintenance-check.py --done <aufgabe>[,<aufgabe>...] [--date YYYY-MM-DD]
#       Setzt `letzter_lauf` (Default heute) und berechnet `naechster_lauf` = letzter_lauf + intervall_tage
#       (ereignisgesteuerte Aufgaben bekommen `naechster_lauf: null`). `--done alle` trifft alle Aufgaben mit
#       gesetztem intervall_tage. Unbekannte Aufgabe(n) -> Exit 2 mit Liste der bekannten Aufgaben. Ein
#       leeres Argument (`--done ""`) faellt NICHT still auf --check zurueck, sondern -> Exit 2 mit Hinweis.
#   python .claude/scripts/maintenance-check.py --set <aufgabe>=<tage>[,<aufgabe>=<tage>...]
#       Setzt/aendert Intervalle (Tage als Zahl; 0, leer, 'null' oder '-' = ereignisgesteuert). Legt fehlende
#       Aufgaben an (mit `letzter_lauf`/`naechster_lauf: null`). Ist bereits ein `letzter_lauf` gesetzt, wird
#       `naechster_lauf` mit dem neuen Intervall neu berechnet. Ein leeres Argument (`--set ""`) faellt NICHT
#       still auf --check zurueck, sondern -> Exit 2 mit Hinweis.
#   python .claude/scripts/maintenance-check.py --status
#       Wie --list, zusaetzlich Pfad der Statusdatei und ob die Wartung im Projekt ueberhaupt eingerichtet ist.
#
# status.json-Schema:
#   {"aufgaben": {"<name>": {"intervall_tage": <int|null>, "letzter_lauf": "YYYY-MM-DD"|null,
#                             "naechster_lauf": "YYYY-MM-DD"|null}, ...}, "_hinweis": "..."}
#   `intervall_tage: null` = ereignisgesteuert (laeuft nur auf Zuruf, nie automatisch faellig). Eine hier
#   fehlende Aufgabe gilt als deaktiviert. Datei wird immer mit indent=2, LF, ensure_ascii=False geschrieben,
#   unbekannte Top-Level-Felder bleiben erhalten.
#
# Exit-Codes: 0 = ok (--check IMMER, auch bei Faelligkeit), 2 = Usage-/Validierungsfehler (--done/--set).
# Root kommt aus CLAUDE_PROJECT_DIR, sonst aus dem Pfad dieses Scripts (parents[2]). Sieht das Zielverzeichnis
# nicht nach einem Projekt aus diesem Template aus (AGENTS.md fehlt), ist JEDER Aufruf still Exit 0 - ein
# Fehler dieses Scripts darf nie mit Traceback nach aussen dringen (main() laeuft komplett in try/except).

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

STATUS_REL = Path(".claude") / "maintenance" / "status.json"
DATE_FMT = "%Y-%m-%d"

_HINWEIS = (
    "Aufgabe je Schluessel unter 'aufgaben'. intervall_tage: null = ereignisgesteuert (laeuft nur auf "
    "Zuruf, nie automatisch faellig). Fehlt eine Aufgabe hier, ist sie deaktiviert. Nach einem Lauf setzt "
    "der Orchestrator (bzw. 'maintenance-check.py --done <aufgabe>') letzter_lauf = heute und "
    "naechster_lauf = heute + intervall_tage (bei null nur letzter_lauf). Datumsformat YYYY-MM-DD. Siehe "
    ".claude/maintenance/README.md."
)


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _parse_date(s: str) -> date:
    return datetime.strptime(s, DATE_FMT).date()


def _as_date(value):
    """Duldsame Datumslesung: date oder None. Muss JEDEN Wert vertragen (falscher Typ, Unsinn, leer) -
    eine von Hand verdorbene status.json darf --check nie zum Fehler machen (Hook liest nur bei Exit 0)."""
    if not isinstance(value, str):
        return None
    try:
        return _parse_date(value)
    except ValueError:
        return None


def _intervall(task: dict):
    """intervall_tage als positive ganze Zahl oder None - auch wenn im JSON Text, 0 oder Negatives steht."""
    value = task.get("intervall_tage")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _plus_tage(d: date, tage: int):
    """d + tage, aber None statt Absturz bei absurden Intervallen (jenseits von date.max)."""
    try:
        return d + timedelta(days=tage)
    except (OverflowError, ValueError, OSError):
        return None


def _faellig_ab(task: dict):
    """Datum, ab dem die Aufgabe faellig ist: naechster_lauf, ersatzweise letzter_lauf + intervall_tage.
    None = kein Termin bestimmbar (ereignisgesteuert oder noch nie gelaufen)."""
    naechster = _as_date(task.get("naechster_lauf"))
    if naechster:
        return naechster
    intervall = _intervall(task)
    letzter = _as_date(task.get("letzter_lauf"))
    if intervall and letzter:
        return _plus_tage(letzter, intervall)
    return None


def _fmt_date(d: date) -> str:
    return d.strftime(DATE_FMT)


def _today() -> date:
    return date.today()


def load_status_raw(root: Path):
    """Gibt (data, path) zurueck. data ist None, wenn die Datei/der Ordner fehlt oder das JSON kein Objekt
    ergibt (kaputte Datei) - beides fuer --check ein stiller, kein fehlerhafter Zustand."""
    path = root / STATUS_REL
    if not path.exists():
        return None, path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, path
    if not isinstance(data, dict):
        return None, path
    return data, path


def save_status(root: Path, data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _aufgaben(data: dict) -> dict:
    aufgaben = data.get("aufgaben")
    return aufgaben if isinstance(aufgaben, dict) else {}


# ---------------------------------------------------------------------------
# Faelligkeit
# ---------------------------------------------------------------------------


def _is_faellig(task: dict, today: date) -> bool:
    faellig_ab = _faellig_ab(task)
    if faellig_ab:
        return faellig_ab <= today
    # Kein Termin bestimmbar: zeitgesteuert und noch nie gelaufen ist faellig.
    return bool(_intervall(task)) and not task.get("letzter_lauf")


def _status_text(task: dict, today: date) -> str:
    # Muss dieselbe Frage beantworten wie _is_faellig - sonst meldet --list "faellig", waehrend --check
    # (und damit der SessionStart-Hook) schweigt.
    faellig_ab = _faellig_ab(task)
    if faellig_ab and faellig_ab <= today:
        return "faellig"
    intervall = _intervall(task)
    if not intervall:
        return "ereignisgesteuert"
    if not task.get("letzter_lauf"):
        return "nie gelaufen"
    if faellig_ab:
        return f"in {(faellig_ab - today).days} Tagen"
    return "kein Termin bestimmbar"  # nur bei absurdem Intervall (jenseits von date.max)


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def cmd_check(root: Path, quiet: bool) -> int:
    # AI-CONFIG.md bleibt seit create-project.py --finish dauerhaft im Projekt - anders als frueher (CONFIG.md
    # wurde geloescht) taugt ihre blosse Existenz daher nicht mehr als Signal. Massgeblich ist jetzt der
    # Vermerk "Einrichtung abgeschlossen am ..." in ihrer ersten Zeile (von --finish gesetzt, gleicher Text
    # wie FINISH_MARKER_TEXT in create-project.py - hier dupliziert, kein Import). Fehlt er, ist das Projekt noch
    # nicht fertig angelegt (Template-Checkout, frischer Klon vor /create-project, oder /create-project ohne
    # --finish). Dann waeren alle Aufgaben "noch nie gelaufen" - das ist keine Faelligkeit, sondern der
    # Auslieferungszustand, und wuerde jede Sitzung mit einer sinnlosen Meldung eroeffnen.
    config_path = root / "AI-CONFIG.md"
    if config_path.exists():
        try:
            erste_zeile = config_path.read_text(encoding="utf-8-sig").split("\n", 1)[0]
        except OSError:
            erste_zeile = ""
        if "Einrichtung abgeschlossen am" not in erste_zeile:
            return 0
    data, _path = load_status_raw(root)
    if data is None:
        return 0
    aufgaben = _aufgaben(data)
    if not aufgaben:
        return 0

    today = _today()
    faellig = [(name, task) for name, task in aufgaben.items() if isinstance(task, dict) and _is_faellig(task, today)]
    if not faellig:
        return 0

    names = ", ".join(n for n, _ in faellig)
    body = []
    for name, task in faellig:
        intervall = _intervall(task)
        letzter = _as_date(task.get("letzter_lauf"))
        if not letzter:
            body.append(f"  {name}: noch nie gelaufen (Intervall {intervall} Tage)")
            continue
        faellig_ab = _faellig_ab(task)
        if faellig_ab:
            tage_txt = f"seit {max((today - faellig_ab).days, 0)} Tag(en) faellig"
        else:
            tage_txt = "faellig"
        body.append(f"  {name}: {tage_txt} (letzter Lauf {_fmt_date(letzter)}, Intervall {intervall} Tage)")

    header = f"Wartung faellig: {names}"
    footer = "Starten: Skill /run-maintenance bzw. python .claude/scripts/maintenance-check.py --list"
    available = 8 - 2  # Kopf- und Schlusszeile
    if len(body) > available:
        shown = body[: max(available - 1, 0)]
        shown.append(f"  ... (+{len(body) - len(shown)} weitere, siehe --list)")
    else:
        shown = body
    print("\n".join([header] + shown + [footer]))
    return 0


# ---------------------------------------------------------------------------
# --list / --status
# ---------------------------------------------------------------------------


def cmd_list(root: Path) -> int:
    data, path = load_status_raw(root)
    if data is None:
        print("Wartung ist in diesem Projekt nicht eingerichtet (status.json fehlt oder ist ungueltig).")
        print(f"Pfad: {path}")
        return 0
    aufgaben = _aufgaben(data)
    if not aufgaben:
        print("Wartung ist eingerichtet, aber keine Aufgaben konfiguriert (status.json ohne 'aufgaben').")
        return 0

    today = _today()
    print("Wartungsaufgaben:")
    for name, task in aufgaben.items():
        if not isinstance(task, dict):
            continue
        intervall = _intervall(task)
        intervall_txt = str(intervall) + " Tage" if intervall else "ereignisgesteuert"
        letzter_d = _as_date(task.get("letzter_lauf"))
        letzter = _fmt_date(letzter_d) if letzter_d else "nie"
        faellig_ab = _faellig_ab(task)
        naechster = _fmt_date(faellig_ab) if faellig_ab else "-"
        status = _status_text(task, today)
        print(f"  {name}: Intervall {intervall_txt}, letzter Lauf {letzter}, naechster Lauf {naechster}, Status {status}")
    return 0


def cmd_status(root: Path) -> int:
    path = root / STATUS_REL
    maint_dir = root / ".claude" / "maintenance"
    print(f"Statusdatei: {path}")
    print(f"Wartung im Projekt vorhanden: {'ja' if maint_dir.exists() else 'nein'}")
    return cmd_list(root)


# ---------------------------------------------------------------------------
# --done
# ---------------------------------------------------------------------------


def cmd_done(root: Path, aufgaben_arg: str, date_arg: str) -> int:
    data, path = load_status_raw(root)
    if data is None:
        print(
            "Fehler: status.json fehlt oder ist ungueltig - zuerst --set verwenden oder Wartung ueber "
            "AI-CONFIG.md aktivieren.",
            file=sys.stderr,
        )
        return 2

    aufgaben = data.setdefault("aufgaben", {})
    if not isinstance(aufgaben, dict):
        aufgaben = {}
        data["aufgaben"] = aufgaben

    if aufgaben_arg.strip().lower() == "alle":
        names = [n for n, t in aufgaben.items() if isinstance(t, dict) and t.get("intervall_tage")]
        if not names:
            print("Keine zeitgesteuerten Aufgaben vorhanden (alle sind ereignisgesteuert oder es gibt keine).")
            return 0
    else:
        names = [n.strip() for n in aufgaben_arg.split(",") if n.strip()]

    unknown = [n for n in names if n not in aufgaben]
    if unknown:
        print(f"Fehler: unbekannte Aufgabe(n): {', '.join(unknown)}", file=sys.stderr)
        print(f"Bekannte Aufgaben: {', '.join(sorted(aufgaben)) if aufgaben else '(keine)'}", file=sys.stderr)
        return 2

    if date_arg:
        try:
            today = _parse_date(date_arg)
        except ValueError:
            print(f"Fehler: --date {date_arg} ist kein gueltiges Datum (YYYY-MM-DD).", file=sys.stderr)
            return 2
    else:
        today = _today()

    for name in names:
        task = aufgaben.get(name)
        if not isinstance(task, dict):
            task = {"intervall_tage": None, "letzter_lauf": None, "naechster_lauf": None}
        task["letzter_lauf"] = _fmt_date(today)
        intervall = _intervall(task)
        naechster = _plus_tage(today, intervall) if intervall else None
        task["naechster_lauf"] = _fmt_date(naechster) if naechster else None
        aufgaben[name] = task

    save_status(root, data, path)
    print("Aktualisiert:")
    for name in names:
        task = aufgaben[name]
        print(f"  {name}: letzter Lauf {task.get('letzter_lauf')}, naechster Lauf {task.get('naechster_lauf') or '-'}")
    return 0


# ---------------------------------------------------------------------------
# --set
# ---------------------------------------------------------------------------


EREIGNISGESTEUERT_WERTE = {"0", "", "null", "none", "-"}


def cmd_set(root: Path, set_arg: str) -> int:
    data, path = load_status_raw(root)
    if data is None:
        data = {"aufgaben": {}, "_hinweis": _HINWEIS}
        path = root / STATUS_REL

    aufgaben = data.setdefault("aufgaben", {})
    if not isinstance(aufgaben, dict):
        aufgaben = {}
        data["aufgaben"] = aufgaben

    pairs = [p.strip() for p in set_arg.split(",") if p.strip()]
    if not pairs:
        print("Fehler: --set benoetigt mindestens ein Aufgabe=Tage.", file=sys.stderr)
        return 2

    changed = []
    for pair in pairs:
        if "=" not in pair:
            print(f"Fehler: '{pair}' ist kein gueltiges Aufgabe=Tage-Paar.", file=sys.stderr)
            return 2
        name, val = (part.strip() for part in pair.split("=", 1))
        if not name:
            print(f"Fehler: '{pair}' hat keinen Aufgabennamen.", file=sys.stderr)
            return 2
        if val.lower() in EREIGNISGESTEUERT_WERTE:
            intervall = None
        else:
            try:
                intervall = int(val)
            except ValueError:
                print(f"Fehler: '{pair}' - Tage muessen eine Zahl, 0, 'null' oder '-' sein.", file=sys.stderr)
                return 2
            if intervall < 0:
                print(f"Fehler: '{pair}' - Tage duerfen nicht negativ sein.", file=sys.stderr)
                return 2
            if intervall == 0:
                intervall = None

        task = aufgaben.get(name)
        if not isinstance(task, dict):
            task = {"intervall_tage": None, "letzter_lauf": None, "naechster_lauf": None}
        task["intervall_tage"] = intervall
        if intervall and _as_date(task.get("letzter_lauf")):
            naechster = _plus_tage(_as_date(task["letzter_lauf"]), intervall)
            task["naechster_lauf"] = _fmt_date(naechster) if naechster else None
        elif not intervall:
            task["naechster_lauf"] = None
        aufgaben[name] = task
        changed.append(name)

    if "_hinweis" not in data:
        data["_hinweis"] = _HINWEIS
    save_status(root, data, path)
    print("Intervalle gesetzt:")
    for name in changed:
        intervall = aufgaben[name].get("intervall_tage")
        print(f"  {name}: {(str(intervall) + ' Tage') if intervall else 'ereignisgesteuert'}")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="maintenance-check.py",
        description="Faelligkeit der wiederkehrenden Wartung (.claude/maintenance/status.json) pruefen/pflegen.",
    )
    parser.add_argument("--check", action="store_true", help="Faellige Aufgaben melden (Default)")
    parser.add_argument("--quiet", action="store_true", help="Fuer den Hook-Aufruf - Verhalten wie --check")
    parser.add_argument("--list", action="store_true", help="Alle Aufgaben mit Status anzeigen")
    parser.add_argument("--status", action="store_true", help="Wie --list, plus Pfad/Einrichtungsstatus")
    parser.add_argument("--done", metavar="AUFGABE[,AUFGABE...]|alle", help="letzter_lauf/naechster_lauf fortschreiben")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Datum fuer --done (Default heute)")
    parser.add_argument("--set", metavar="AUFGABE=TAGE[,AUFGABE=TAGE...]", help="Intervalle setzen/aendern")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _find_root()

    if not (root / "AGENTS.md").exists():
        return 0  # kein Projekt aus diesem Template - still, kein Fehler

    if args.done is not None:
        if not args.done.strip():
            print(
                "Fehler: --done erwartet AUFGABE[,AUFGABE...] oder 'alle', z.B. --done kurz,docs",
                file=sys.stderr,
            )
            return 2
        return cmd_done(root, args.done, args.date)
    if args.set is not None:
        if not args.set.strip():
            print(
                "Fehler: --set erwartet AUFGABE=TAGE[,AUFGABE=TAGE...], z.B. --set docs=7,deps=0",
                file=sys.stderr,
            )
            return 2
        return cmd_set(root, args.set)
    if args.status:
        return cmd_status(root)
    if args.list:
        return cmd_list(root)
    return cmd_check(root, args.quiet)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"maintenance-check: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
