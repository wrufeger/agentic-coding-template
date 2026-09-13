#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Bausteine unter `docs/project/coding_rules.d/` verwalten (ein Baustein je Sprache/Framework,
#        ergaenzend zu den generischen Regeln in `docs/project/coding_rules.md`). Ein Projekt behaelt nur die
#        passenden Bausteine, kann aber jederzeit weitere aus dem Template nachladen. Pflegt dabei den
#        maschinell geschriebenen Indexblock (`<!-- guidelines:start -->` ... `<!-- guidelines:end -->`) in
#        `docs/project/coding_rules.md` § "Vorgefertigte Regelsaetze". Siehe
#        `docs/project/coding_rules.d/README.md`. Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf:
#   python .claude/scripts/guidelines.py [--list]
#       (Default) Zeigt aktive Bausteine (Dateien in coding_rules.d/, ohne README.md) und - falls ermittelbar
#       (Template-Remote/-Branch erreichbar) - die im Template zusaetzlich verfuegbaren. Immer Exit 0.
#   python .claude/scripts/guidelines.py --available
#       Nur die im Template verfuegbaren Kennungen, eine je Zeile (fuer Skripte/Assistenten) - Vereinigung aus
#       lokalem Ordner und der Template-Quelle (siehe unten). Keine Quelle ermittelbar: Hinweis, Exit 0.
#   python .claude/scripts/guidelines.py --add <kennung>[,<kennung>...]
#       Holt fehlende Bausteine aus dem Template und schreibt sie nach coding_rules.d/. Bereits vorhandene
#       werden NICHT ueberschrieben (nur gemeldet). Unbekannte Kennung(en) -> Exit 2 mit Liste der
#       verfuegbaren Kennungen, VOR jeder Aenderung (auch wenn andere Kennungen im selben Aufruf bekannt
#       waeren - alles oder nichts). Schreibt danach den Indexblock neu.
#   python .claude/scripts/guidelines.py --remove <kennung>[,<kennung>...]
#       Loescht die Baustein-Datei(en) und schreibt den Indexblock neu. Nicht vorhandene Kennung(en) werden
#       nur gemeldet, Exit bleibt 0.
#   python .claude/scripts/guidelines.py --sync
#       Schreibt nur den Indexblock in coding_rules.md neu (nach manuellem Kopieren/Loeschen von Dateien).
#       Fehlt der Block komplett, wird die Sektion "## Vorgefertigte Regelsaetze" einmalig VOR "## Stack-
#       spezifisch" neu angelegt (steht die Ueberschrift nicht in der Datei: am Dateiende).
#
# Kennungen: Dateiname in coding_rules.d/ in Kleinbuchstaben ohne ".md" (z.B. "php.md" -> Kennung "php").
# "README.md" zaehlt nie als Baustein.
#
# Quelle fuer "im Template verfuegbar" (in dieser Reihenfolge, Ergebnisse werden vereinigt):
#   (a) lokaler Ordner docs/project/coding_rules.d/ - direkt im Template-Checkout selbst ist das bereits der
#       vollstaendige Katalog.
#   (b) `git ls-tree --name-only <ref>:docs/project/coding_rules.d`, <ref> aus derselben compare_ref-Logik
#       wie `update-template.py` (Remote-Branch, sonst gleichnamiger lokaler Branch; update-template.py wird
#       dafuer als Modul geladen wie setup-lib.py es tut - nicht dupliziert). Kein Remote/Branch
#       ermittelbar oder Fetch schlaegt fehl: (b) liefert nichts, ohne Fehler - (a) traegt trotzdem, was
#       lokal schon da ist. `--list` funktioniert dann weiter (nur ohne "zusaetzlich verfuegbar"-Angabe);
#       `--add` einer noch nicht lokalen Kennung meldet dann verstaendlich, dass die Quelle fehlt (Exit 2).
#
# Indexblock: alphabetisch nach Kennung, je Zeile `- [<Anzeigename>](coding_rules.d/<kennung>.md) —
# <Kurzbeschreibung>`. Anzeigename/Kurzbeschreibung werden aus dem Baustein gelesen: erste `# `-Ueberschrift
# (Teil nach dem Gedankenstrich/Bindestrich) und die erste nicht-leere Zeile darunter (auf 80 Zeichen
# gekuerzt). Sind keine Bausteine aktiv, steht zwischen den Markern ein Hinweistext statt einer Liste.
#
# Dateien: neu angelegte Baustein-Dateien immer LF/UTF-8 ohne BOM. Beim Neuschreiben des Indexblocks in einer
# BESTEHENDEN coding_rules.md bleibt deren eigene Zeilenendung (LF/CRLF) erhalten - nur der Blockinhalt
# aendert sich, der Rest der Datei bleibt zeichengleich.
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungs-/Argumentfehler (fehlendes AGENTS.md, unbekannte Kennung bei --add,
# ungueltige Argumente). Nie ein Traceback nach aussen - main() laeuft komplett in try/except.

import argparse
import importlib.util
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

CODING_RULES_D_REL = Path("docs") / "project" / "coding_rules.d"
CODING_RULES_MD_REL = Path("docs") / "project" / "coding_rules.md"
MARK_START = "<!-- guidelines:start -->"
MARK_END = "<!-- guidelines:end -->"
STACK_HEADING = "## Stack-spezifisch"
LEER_HINWEIS = "*(noch keine — `python .claude/scripts/guidelines.py --add <kennung>` ergänzt welche)*"

NEUE_SEKTION = """## Vorgefertigte Regelsätze

Technologiespezifische Regeln liegen als Bausteine unter `coding_rules.d/` — ein Baustein je Sprache oder
Framework. Verwaltet werden sie mit `python .claude/scripts/guidelines.py` (`--list`, `--add <kennung>`,
`--remove <kennung>`); der folgende Block wird dabei automatisch geschrieben, hier nichts von Hand ändern.

{start}
{{body}}
{end}
""".format(start=MARK_START, end=MARK_END)


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    import os

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _load_template_update_module():
    """Laedt update-template.py als Modul (gleicher Ordner) - dieselbe Quelle fuer compare_ref/run_git wie
    setup-lib.py, statt sie hier zu duplizieren."""
    tu_path = Path(__file__).resolve().parent / "update-template.py"
    spec = importlib.util.spec_from_file_location("_template_update_for_guidelines", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Lokale Bausteine
# ---------------------------------------------------------------------------


def local_identifiers(root: Path):
    """Sortierte Liste der Kennungen (Dateiname ohne .md, klein) unter coding_rules.d/, ohne README.md."""
    d = root / CODING_RULES_D_REL
    if not d.is_dir():
        return []
    out = []
    for fp in d.glob("*.md"):
        if fp.name.lower() == "readme.md":
            continue
        out.append(fp.stem.lower())
    return sorted(out)


def _parse_block_meta(path: Path):
    """(anzeigename, kurzbeschreibung) aus einem Baustein lesen - erste `# `-Ueberschrift (Teil nach dem
    Gedankenstrich/Bindestrich) und die erste nicht-leere Zeile darunter (auf 80 Zeichen gekuerzt). Robust
    gegen fehlende/unerwartete Struktur - liefert dann Platzhalter statt abzustuerzen."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path.stem, ""
    lines = text.splitlines()
    heading_idx = None
    heading_text = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            heading_idx = i
            heading_text = stripped[2:].strip()
            break
    if heading_text is None:
        return path.stem, ""

    if "—" in heading_text:
        anzeigename = heading_text.split("—", 1)[1].strip()
    elif " - " in heading_text:
        anzeigename = heading_text.split(" - ", 1)[1].strip()
    else:
        anzeigename = heading_text
    if not anzeigename:
        anzeigename = path.stem

    beschreibung = ""
    for line in lines[heading_idx + 1 :]:
        stripped = line.strip()
        if stripped:
            beschreibung = stripped
            break
    if len(beschreibung) > 80:
        beschreibung = beschreibung[:79].rstrip() + "…"
    return anzeigename, beschreibung


# ---------------------------------------------------------------------------
# Template-Quelle (Remote/Branch)
# ---------------------------------------------------------------------------


def _remote_identifiers(root: Path, tu):
    """(liste_oder_None, fehlermeldung_oder_None). None = Quelle nicht ermittelbar/erreichbar (kein Fehler
    fuer --list/--available - dort wird das nur vermerkt). Leere Liste = Quelle erreichbar, aber
    coding_rules.d dort (noch) leer/nicht vorhanden - kein Fehler."""
    cfg, _path = tu.load_template_json(root)
    ref, fetch_noetig = tu.compare_ref(root, cfg)
    if ref is None:
        return None, "kein Template-Remote/-Branch gefunden (siehe 'update-template.py --status')"

    if fetch_noetig:
        remote = cfg.get("template_remote") or "template"
        try:
            res_fetch = tu.run_git(root, ["fetch", remote], timeout=20)
        except Exception as e:  # noqa: BLE001 - Netzwerk-/Timeoutfehler duerfen nicht durchschlagen
            return None, f"'git fetch {remote}' fehlgeschlagen: {e}"
        if res_fetch.returncode != 0:
            return None, f"'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}"

    res_verify = tu.run_git(root, ["rev-parse", "--verify", "--quiet", ref])
    if res_verify.returncode != 0:
        return None, f"Ref '{ref}' nicht aufloesbar"

    res_ls = tu.run_git(root, ["ls-tree", "--name-only", f"{ref}:{CODING_RULES_D_REL.as_posix()}"])
    if res_ls.returncode != 0:
        # Pfad existiert dort (noch) nicht - kein Fehler, nur ein leerer Katalog.
        return [], None

    out = []
    for line in res_ls.stdout.splitlines():
        name = line.strip()
        if name.lower().endswith(".md") and name.lower() != "readme.md":
            out.append(name[: -len(".md")].lower())
    return sorted(set(out)), None


def _catalog(root: Path, tu):
    """(katalog_sortiert, remote_liste_oder_None, remote_fehler_oder_None). katalog = lokale Kennungen
    vereinigt mit den Template-Kennungen (falls ermittelbar)."""
    local = set(local_identifiers(root))
    remote, err = _remote_identifiers(root, tu)
    catalog = local if remote is None else local | set(remote)
    return sorted(catalog), remote, err


# ---------------------------------------------------------------------------
# Indexblock in coding_rules.md
# ---------------------------------------------------------------------------


def _block_body(root: Path) -> str:
    ids = local_identifiers(root)
    if not ids:
        return LEER_HINWEIS
    d = root / CODING_RULES_D_REL
    lines = []
    for kennung in ids:
        anzeigename, beschreibung = _parse_block_meta(d / f"{kennung}.md")
        suffix = f" — {beschreibung}" if beschreibung else ""
        lines.append(f"- [{anzeigename}](coding_rules.d/{kennung}.md){suffix}")
    return "\n".join(lines)


def _detect_eol(raw: bytes) -> str:
    return "\r\n" if b"\r\n" in raw else "\n"


def sync_index(root: Path) -> str:
    """Schreibt den Indexblock in coding_rules.md neu, ohne den Rest der Datei anzutasten (auch nicht deren
    Zeilenendung). Existiert die Datei/der Block nicht, wird die Sektion "## Vorgefertigte Regelsaetze"
    einmalig angelegt (vor "## Stack-spezifisch", sonst am Dateiende). Gibt einen kurzen Statustext zurueck."""
    path = root / CODING_RULES_MD_REL
    body = _block_body(root)

    if not path.exists():
        return f"Hinweis: {CODING_RULES_MD_REL.as_posix()} fehlt - Indexblock nicht geschrieben."

    raw = path.read_bytes()
    eol = _detect_eol(raw)
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")

    start_idx = text.find(MARK_START)
    end_idx = text.find(MARK_END)
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        new_text = text[:start_idx] + MARK_START + "\n" + body + "\n" + text[end_idx:]
        status = "Indexblock aktualisiert."
    else:
        section = NEUE_SEKTION.replace("{body}", body)
        heading_idx = text.find(STACK_HEADING)
        if heading_idx != -1:
            new_text = text[:heading_idx] + section + "\n" + text[heading_idx:]
        else:
            sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
            new_text = text + sep + section
        status = "Sektion 'Vorgefertigte Regelsätze' neu angelegt."

    if eol == "\r\n":
        new_text = new_text.replace("\n", "\r\n")
    path.write_bytes(new_text.encode("utf-8"))
    return status


# ---------------------------------------------------------------------------
# --list / --available
# ---------------------------------------------------------------------------


def cmd_list(root: Path, tu) -> int:
    active = local_identifiers(root)
    catalog, remote, err = _catalog(root, tu)

    print("Aktive Bausteine:")
    if active:
        for kennung in active:
            anzeigename, _ = _parse_block_meta(root / CODING_RULES_D_REL / f"{kennung}.md")
            print(f"  - {kennung} ({anzeigename})")
    else:
        print("  (keine)")

    if remote is None:
        print(f"Zusätzlich im Template verfügbar: nicht ermittelbar ({err})")
    else:
        extra = sorted(set(catalog) - set(active))
        print("Zusätzlich im Template verfügbar: " + (", ".join(extra) if extra else "(keine weiteren)"))
    return 0


def cmd_available(root: Path, tu) -> int:
    catalog, _remote, err = _catalog(root, tu)
    if not catalog:
        hinweis = f" ({err})" if err else ""
        print(f"Keine Quelle ermittelbar - weder lokale Bausteine noch Template-Katalog erreichbar{hinweis}.")
        return 0
    for kennung in catalog:
        print(kennung)
    return 0


# ---------------------------------------------------------------------------
# --add / --remove / --sync
# ---------------------------------------------------------------------------


def _parse_kennungen(arg: str):
    seen = []
    for part in arg.split(","):
        k = part.strip().lower()
        if k and k not in seen:
            seen.append(k)
    return seen


def cmd_add(root: Path, tu, arg: str) -> int:
    requested = _parse_kennungen(arg)
    if not requested:
        print("Fehler: --add benoetigt mindestens eine Kennung.", file=sys.stderr)
        return 2

    active = set(local_identifiers(root))
    catalog, remote, err = _catalog(root, tu)
    catalog_set = set(catalog)

    unknown = [k for k in requested if k not in catalog_set]
    if unknown:
        print(f"Fehler: unbekannte Kennung(en): {', '.join(unknown)}", file=sys.stderr)
        if catalog:
            print(f"Verfuegbare Kennungen: {', '.join(catalog)}", file=sys.stderr)
        else:
            print("Keine Kennungen verfuegbar (weder lokal noch im Template).", file=sys.stderr)
        if remote is None:
            print(
                f"Hinweis: Template-Quelle nicht erreichbar ({err}) - ggf. sind das noch unbekannte "
                "Kennungen dort, die hier nur deshalb fehlen.",
                file=sys.stderr,
            )
        return 2

    already = [k for k in requested if k in active]
    to_fetch = [k for k in requested if k not in active]

    # Erst ALLES holen, bevor irgendetwas geschrieben wird - schlaegt eine Kennung fehl, bleibt der
    # Ordner unveraendert (kein Teilzustand).
    fetched = {}
    if to_fetch:
        if remote is None:
            print(
                f"Fehler: Quelle fehlt ({err}) - '{', '.join(to_fetch)}' liegt nicht lokal vor und kann "
                "nicht aus dem Template geholt werden.",
                file=sys.stderr,
            )
            return 2
        cfg, _path = tu.load_template_json(root)
        ref, _fetch_noetig = tu.compare_ref(root, cfg)
        for kennung in to_fetch:
            res = tu.run_git(root, ["show", f"{ref}:{CODING_RULES_D_REL.as_posix()}/{kennung}.md"])
            if res.returncode != 0:
                print(f"Fehler: Baustein '{kennung}' im Template nicht lesbar: {res.stderr.strip()}", file=sys.stderr)
                return 2
            fetched[kennung] = res.stdout

    d = root / CODING_RULES_D_REL
    d.mkdir(parents=True, exist_ok=True)
    for kennung in to_fetch:
        (d / f"{kennung}.md").write_text(fetched[kennung], encoding="utf-8", newline="\n")

    if already:
        print("Schon vorhanden (unveraendert): " + ", ".join(already))
    if to_fetch:
        print("Hinzugefuegt: " + ", ".join(to_fetch))

    status = sync_index(root)
    print(status)
    return 0


def cmd_remove(root: Path, tu, arg: str) -> int:
    requested = _parse_kennungen(arg)
    if not requested:
        print("Fehler: --remove benoetigt mindestens eine Kennung.", file=sys.stderr)
        return 2

    d = root / CODING_RULES_D_REL
    removed, missing = [], []
    for kennung in requested:
        fp = d / f"{kennung}.md"
        if fp.exists():
            fp.unlink()
            removed.append(kennung)
        else:
            missing.append(kennung)

    if removed:
        print("Entfernt: " + ", ".join(removed))
    if missing:
        print("Nicht vorhanden (nichts zu tun): " + ", ".join(missing))

    status = sync_index(root)
    print(status)
    return 0


def cmd_sync(root: Path) -> int:
    status = sync_index(root)
    print(status)
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guidelines.py",
        description="Bausteine unter docs/project/coding_rules.d/ verwalten und den Indexblock in coding_rules.md pflegen.",
    )
    parser.add_argument("--list", action="store_true", help="Aktive + zusaetzlich verfuegbare Bausteine anzeigen (Default)")
    parser.add_argument("--available", action="store_true", help="Nur verfuegbare Kennungen, eine je Zeile")
    parser.add_argument("--add", metavar="KENNUNG[,KENNUNG...]", help="Baustein(e) aus dem Template holen")
    parser.add_argument("--remove", metavar="KENNUNG[,KENNUNG...]", help="Baustein(e) entfernen")
    parser.add_argument("--sync", action="store_true", help="Nur den Indexblock neu schreiben")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = _find_root()
    if not (root / "AGENTS.md").exists():
        print(f"Fehler: '{root}' sieht nicht nach einem Projekt aus diesem Template aus (AGENTS.md fehlt).", file=sys.stderr)
        return 2

    if args.add:
        tu = _load_template_update_module()
        return cmd_add(root, tu, args.add)
    if args.remove:
        tu = _load_template_update_module()
        return cmd_remove(root, tu, args.remove)
    if args.sync:
        return cmd_sync(root)
    if args.available:
        tu = _load_template_update_module()
        return cmd_available(root, tu)

    tu = _load_template_update_module()
    return cmd_list(root, tu)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"guidelines: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
