#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Template-Updates in ein aus diesem Template abgeleitetes Projekt per Git-Merge einspielen, ohne
#        dass echte Werte wieder durch Platzhalter (`{{PROJEKTNAME}}` usw.) ersetzt werden. Verwaltet dazu
#        `.claude/template.json` (Remote/Branch des Templates, zuletzt eingespielter Basis-Commit, die
#        eingesetzten Platzhalterwerte, Dateien/Ordner, deren Projektfassung bei Konflikten immer gewinnt,
#        Update-Historie). Siehe AGENTS.md § "Template-Herkunft und Updates", CLAUDE.md § 2 (Skill
#        `/update-template`), docs/ai/checklists.md § "Template-Update". Reine Python-Stdlib, kein Paket
#        noetig.
#
# Aufruf:
#   python .claude/scripts/update-template.py --init [--url URL] [--base HASH] [--set KEY=WERT ...]
#       Legt Remote "template" an (falls noetig), ermittelt/uebernimmt den Basis-Commit, speichert Werte.
#   python .claude/scripts/update-template.py --set KEY=WERT [--set KEY=WERT ...]
#       Nur Platzhalterwerte schreiben (ohne Remote/Basis-Commit anzufassen).
#   python .claude/scripts/update-template.py --check [--quiet]
#       Prueft, ob das Template neuer ist als der gespeicherte Basis-Commit (mit fetch, Timeout 20s).
#       Exit 0 = aktuell/nicht konfiguriert (bei --quiet), 2 = nicht konfiguriert/Netzwerkfehler (ohne
#       --quiet), 3 = Update verfuegbar (Ausgabe: Commits, geaenderte Dateien, keep_local-Markierung).
#   python .claude/scripts/update-template.py --apply [--commit]
#       Mergt template/<branch> in den Arbeitsbaum (git merge --no-ff --no-commit). Schlaegt der Merge aus
#       einem anderen Grund als offenen Konflikten fehl (z.B. "not something we can merge"), bricht --apply
#       SOFORT ab (Exit 2) - VOR jedem Schreibzugriff auf .claude/template.json, damit ein sauberer
#       Arbeitsbaum fuer den naechsten Versuch zurueckbleibt. Erst danach werden Konflikte in
#       .claude/template.json feldweise gemergt (auch "both added" beim Bootstrap, siehe unten):
#       base_commit/updates/template_remote/template_branch/template_url/is_template immer aus der
#       Projektfassung OHNE Rueckfall auf das Template, wenn das Feld dort fehlt (fehlt es im Projekt, soll
#       es fehlen); values feldweise (Projektwert gewinnt je Schluessel, neue Platzhalter aus dem Template
#       werden mit null ergaenzt, damit sie nicht unersetzt in Zieldateien stehen bleiben); keep_local/
#       no_replace als Vereinigung (Projekt zuerst, dann neue Template-Eintraege) - unabhaengig von
#       keep_local selbst. Schlaegt das Parsen einer Seite fehl, faellt es auf das alte Verhalten zurueck
#       (Projektfassung komplett). Konflikte vom Typ "DD" (von beiden geloescht)
#       werden immer automatisch bereinigt (unstrittig). Konflikte vom Typ "DU" (vom Projekt geloescht, im
#       Template geaendert) werden NUR DANN automatisch als "geloescht belassen" entschieden, wenn der Pfad
#       in keep_local steht UND keine Umbenennung erkennbar ist (siehe --conflicts) - das Script darf sonst
#       nicht allein entscheiden, ob die Loeschung bewusst war oder nur eine Umbenennung/Verschiebung ist
#       (typisch: docs/ai/ auf eigene Dateinamen migriert). Sonstige Konflikte in keep_local-Pfaden werden
#       automatisch zugunsten der Projektfassung geloest; alle uebrigen (inkl. offen gelassener DU-Faelle)
#       muessen von Hand geloest werden (Analyse siehe --conflicts, danach --continue). Ohne Konflikte bzw.
#       nach deren Aufloesung: Platzhalter in den vom Merge beruehrten Textdateien (ausser keep_local und
#       no_replace) ersetzen, base_commit/updates fortschreiben, git add.
#   python .claude/scripts/update-template.py --continue [--commit]
#       Nach manueller Konfliktaufloesung: prueft, dass keine Konflikte mehr offen sind, fuehrt den
#       Abschlussschritt von --apply aus.
#   python .claude/scripts/update-template.py --conflicts
#       Nur waehrend eines laufenden Merges (MERGE_HEAD vorhanden, sonst Hinweis + Exit 0): analysiert jeden
#       noch offenen Konflikt fuer den Assistenten (Art, Prioritaetsregel, Zeilenumfang der Aenderung je
#       Seite, Umbenennungs-Kandidat bei "DU" per Git-Rename-Erkennung bzw. Inhaltsaehnlichkeit unter
#       docs/ai/; bei "AU"/"UA" - beide Seiten haben dieselbe Datei verschoben - beide Zielpfade per
#       Git-Rename-Erkennung, passende git-Befehle zum Nachschauen). Schreibt nichts, loest nichts auf -
#       reine Analyse fuer die inhaltliche Zusammenfuehrung, die der Assistent macht.
#   python .claude/scripts/update-template.py --abort
#       Bricht einen laufenden Merge ab (git merge --abort); .claude/template.json bleibt unveraendert.
#   python .claude/scripts/update-template.py --status
#       Zeigt Konfiguration, Remote-URL, base_commit, letztes Update, Anzahl ausstehender Commits (ohne
#       fetch, also ggf. veralteter Stand), ob eine gemeinsame Historie mit base_commit existiert
#       (graft-Status) sowie ob gerade ein Merge laeuft und wie viele Konflikte offen sind.
#   python .claude/scripts/update-template.py --graft
#       Fuer per `apply-template.py` nachgeruestete Projekte (kein gemeinsamer Vorfahr mit dem Template):
#       stellt per leerem Merge (`git merge -s ours --allow-unrelated-histories`) eine gemeinsame Historie
#       zu base_commit her, OHNE den Arbeitsbaum zu veraendern - danach funktionieren --check/--apply wie
#       bei einem per `git clone` angelegten Projekt. Voraussetzung: sauberer Arbeitsbaum, base_commit
#       gesetzt (siehe .claude/template.json), Remote vorher gefetcht (macht `apply-template.py` bzw. der
#       Skill /apply-template bereits). Existiert bereits ein gemeinsamer Vorfahr (`git merge-base HEAD
#       base_commit`), ist --graft ein No-op (Exit 0, Hinweis).
#
# --commit auf --apply/--continue erstellt den Merge-Commit direkt; ohne --commit bleiben die Aenderungen
# gestaged, damit sie vor dem Commit geprueft werden koennen.
#
# Bootstrap (bestehendes Projekt hat dieses Script noch nicht): mit
#   CLAUDE_PROJECT_DIR=<projekt> python <template-checkout>/.claude/scripts/update-template.py --init ...
#   aufrufen - die Root kommt strikt aus CLAUDE_PROJECT_DIR, das Script selbst kann ausserhalb des
#   Projekts liegen. Fehlt .claude/template.json im Projekt, wird intern mit einer leeren Default-
#   Konfiguration gearbeitet (--init legt die Datei an; --check --quiet ohne Datei ist still Exit 0).
#
# keep_local (template.json) = Projektfassung gewinnt BEI KONFLIKTEN und wird nie platzhalter-ersetzt;
# konfliktfreie Template-Aenderungen an diesen Dateien merged git ganz normal mit hinein.
# Vergleichsziel (compare_ref): normalerweise <template_remote>/<template_branch>. Fehlt der Remote,
# existiert aber ein lokaler Branch dieses Namens, wird lokal verglichen und nicht gefetcht - das ist
# der Fall "Projekt entstand als Branch im Template-Checkout" (siehe create-project.py).
# no_replace (template.json) = Dateien, die den Platzhalter selbst dokumentieren; sie werden gemergt, aber
# nie ersetzt.
#
# git laeuft immer nicht-interaktiv (GIT_TERMINAL_PROMPT=0, stdin geschlossen): ein privates Template ohne
# hinterlegten Credential-Helper meldet einen Fehler, statt im Hook auf eine Passworteingabe zu warten.
#
# Exit-Codes: 0 = ok/aktuell (auch --conflicts ohne laufenden Merge bzw. ohne offene Konflikte), 2 =
#             Konfigurations-/Vorbedingungsfehler, 3 = Update verfuegbar (nur --check), 4 = Konflikte offen
#             (nur --apply/--continue). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen
#             dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr. `--check --quiet`
#             schreibt nie auf stdout, ausser es gibt tatsaechlich ein Update.

import argparse
import difflib
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Windows liest sonst in der ANSI-Codepage - Pfade mit Umlauten kaemen als Mojibake an (dasselbe Muster wie
# in ai-log.py/create-project.py; try/except, damit aeltere Python-Versionen ohne reconfigure() nicht scheitern).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DEFAULT_VALUE_KEYS = [
    "PROJEKTNAME",
    "AUFTRAGGEBER",
    "ORCHESTRATOR",
    "STACK",
    "DATUM",
    "INSTALL_BEFEHL",
    "DEV_START_BEFEHL",
    "LINT_BEFEHL",
    "TYPECHECK_BEFEHL",
    "TEST_BEFEHL",
    "E2E_BEFEHL",
]

DEFAULT_KEEP_LOCAL = [
    "docs/project/**",
    "docs/ai/board.md",
    "docs/ai/tasks.md",
    "docs/ai/questions.md",
    "docs/ai/questions_archive.md",
    "docs/ai/ledger.md",
    "docs/ai/backlog.md",
    "docs/ai/tasks_archive.md",
    "README.md",
    "AI-CONFIG.md",
    ".env.example",
    ".github/workflows/ci.yml",
    ".mcp.json.example",
    ".claude/maintenance/status.json",
]

# Dateien, die den Platzhalter selbst dokumentieren (Beispielaufzaehlungen in Checklisten/Skills). Sie werden
# normal gemergt, aber NIE ersetzt - sonst macht ein Update aus "Alle Platzhalter (`{{PROJEKTNAME}}`, ...)"
# die Zeile "Alle Platzhalter (`Kundenportal`, ...)" und die Anleitung ist kaputt.
DEFAULT_NO_REPLACE = [
    ".claude/scripts/create-project.py",
    ".claude/scripts/update-template.py",
]

# Prioritaetsregel je Pfad fuer --conflicts (dieselbe Aussage wie PRIORITY_RULES/priority_label in
# migrate-project.py - dort nachsehen/nachziehen, falls sich die Regeln je aendern - z.B. die
# docs/ai/resources.md-Sonderregel unten). Die Regeln stehen hier nur noch als priority_label()-Logik, ohne
# eigene String-Konstante (die gab es fuer --conflicts nie zu lesen).


def priority_label(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/")
    if norm in ("AGENTS.md", "CLAUDE.md", "docs/ai/checklists.md", "docs/ai/README.md") or norm.startswith(".claude/"):
        return "Template gewinnt, Projektergaenzungen einarbeiten"
    if norm == "docs/project/coding_rules.md":
        return "strengere Regel gewinnt"
    if norm.startswith("docs/project/"):
        return "Projekt gewinnt"
    # docs/ai/resources.md pflegt das TEMPLATE (kuratierte Linksammlung), nicht das Projekt - anders als der
    # Rest von docs/ai/. Ausnahme: der Abschnitt "Eigene Quellen dieses Projekts" am Ende der Datei ist
    # Projekt-Inhalt und bleibt beim Projekt. Muss VOR der allgemeinen docs/ai/-Regel stehen, sonst greift sie
    # nie (die naechste Regel unten ist ebenfalls startswith("docs/ai/") und wuerde sonst zuerst zutreffen).
    if norm == "docs/ai/resources.md":
        return "Template gewinnt, nur Abschnitt 'Eigene Quellen dieses Projekts' bleibt beim Projekt"
    if norm.startswith("docs/ai/"):
        return "Template-Struktur, Projekt-Inhalt"
    if norm in ("README.md", ".gitignore"):
        return "Projekt gewinnt, Template ergaenzt"
    return "abwaegen"


# XY-Status (git status --porcelain=v1) -> (kurzes Ein-Wort-Label fuer die --apply-Konfliktliste,
# ausfuehrliche Art-Beschreibung fuer --conflicts). "DU"/"UD" beziehen sich auf HEAD ("uns", das Projekt);
# beim Merge template -> Projekt ist "uns" also immer das Projekt, "die andere Seite" das Template.
_CONFLICT_KINDS = {
    "UU": ("beide-geaendert", "beide geaendert"),
    "AA": ("beide-neu", "von beiden neu angelegt"),
    "DU": ("geloescht/geaendert", "vom Projekt geloescht, im Template geaendert"),
    "UD": ("geaendert/geloescht", "vom Projekt geaendert, im Template geloescht"),
    "DD": ("beide-geloescht", "von beiden geloescht"),
    "AU": ("neu/geaendert", "vom Projekt neu angelegt, im Template geaendert"),
    "UA": ("geaendert/neu", "vom Projekt geaendert, im Template neu angelegt"),
}


def _conflict_kind_word(code: str) -> str:
    return _CONFLICT_KINDS.get(code, (code or "?", code or "unbekannt"))[0]


def _conflict_art(code: str) -> str:
    return _CONFLICT_KINDS.get(code, (code or "?", code or "unbekannt"))[1]


TEMPLATE_JSON_REL = ".claude/template.json"

_HINWEIS = (
    "Speichert die Herkunft dieses Projekts gegenueber dem Template (Remote, Basis-Commit, eingesetzte "
    "Platzhalterwerte) fuer spaetere Updates per Merge. Wird von `update-template.py --init` befuellt; "
    "`values` nie Secrets."
)


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def run_git(root: Path, args, timeout=None):
    # core.quotePath=false: Pfade mit Umlauten kommen unveraendert zurueck (sonst "docs/\303\234bersicht.md"
    # und der Pfad laesst sich weder oeffnen noch an git zurueckgeben).
    # GIT_TERMINAL_PROMPT=0 + stdin=DEVNULL: nie interaktiv nach Zugangsdaten fragen - im SessionStart-Hook
    # wuerde das haengen, statt eines Fehlers.
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


def _remote_exists(root: Path, remote: str) -> bool:
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    return remote in remotes


def compare_ref(root: Path, cfg: dict):
    """Vergleichsziel fuer Template-Updates -> (ref, fetch_noetig) oder (None, False).

    Normalfall: der Remote-Branch `<remote>/<branch>`. Entsteht das Projekt dagegen als Branch im
    Template-Checkout selbst (create-project.py setzt dann base_commit aus main/master), gibt es keinen
    passenden Remote - dann wird gegen den gleichnamigen LOKALEN Branch verglichen und nicht gefetcht."""
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    if _remote_exists(root, remote):
        return f"{remote}/{branch}", True
    if run_git(root, ["rev-parse", "--verify", "--quiet", branch]).returncode == 0:
        return branch, False
    return None, False


def default_config() -> dict:
    return {
        "template_remote": "template",
        "template_branch": "main",
        "template_url": None,
        "base_commit": None,
        "values": {k: None for k in DEFAULT_VALUE_KEYS},
        "keep_local": list(DEFAULT_KEEP_LOCAL),
        "no_replace": list(DEFAULT_NO_REPLACE),
        "updates": [],
        "_hinweis": _HINWEIS,
    }


def load_template_json(root: Path):
    path = root / TEMPLATE_JSON_REL
    cfg = default_config()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
                if not isinstance(cfg.get("values"), dict):
                    cfg["values"] = default_config()["values"]
                if not isinstance(cfg.get("keep_local"), list):
                    cfg["keep_local"] = list(DEFAULT_KEEP_LOCAL)
                if not isinstance(cfg.get("no_replace"), list):
                    cfg["no_replace"] = list(DEFAULT_NO_REPLACE)
                if not isinstance(cfg.get("updates"), list):
                    cfg["updates"] = []
        except (OSError, ValueError):
            pass  # kaputte/unlesbare Datei -> mit Default weiterarbeiten, wird beim naechsten Save repariert
    return cfg, path


def save_template_json(root: Path, cfg: dict, path: Path) -> None:
    ordered = {
        "template_remote": cfg.get("template_remote", "template"),
        "template_branch": cfg.get("template_branch", "main"),
        "template_url": cfg.get("template_url"),
        "base_commit": cfg.get("base_commit"),
        "values": cfg.get("values") or {},
        "keep_local": cfg.get("keep_local") or list(DEFAULT_KEEP_LOCAL),
        "no_replace": cfg.get("no_replace") if isinstance(cfg.get("no_replace"), list) else list(DEFAULT_NO_REPLACE),
        "updates": cfg.get("updates") or [],
    }
    # Unbekannte Felder (z.B. "is_template", vom Template-Checkout selbst gesetzt) nicht verwerfen - nur
    # die oben bereits behandelten Schluessel und den abschliessenden Hinweistext auslassen.
    for key, value in cfg.items():
        if key in ordered or key == "_hinweis":
            continue
        ordered[key] = value
    ordered["_hinweis"] = cfg.get("_hinweis") or _HINWEIS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)
        f.write("\n")


def matches_keep_local(rel_path: str, patterns) -> bool:
    norm = rel_path.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatchcase(norm, pat):
            return True
    return False


def _short(root: Path, commit: str) -> str:
    if not commit:
        return "?"
    res = run_git(root, ["rev-parse", "--short", commit])
    return res.stdout.strip() if res.returncode == 0 else str(commit)[:7]


# ---------------------------------------------------------------------------
# --init / --set
# ---------------------------------------------------------------------------


def cmd_init(root: Path, cfg: dict, path: Path, url_arg, base_arg, set_pairs) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    if not _remote_exists(root, remote):
        url = url_arg or cfg.get("template_url")
        if not url:
            print(
                f"Fehler: kein Remote '{remote}' vorhanden und keine URL angegeben. Mit --url <URL> "
                f"angeben, oder vorher 'git remote add {remote} <URL>' ausfuehren.",
                file=sys.stderr,
            )
            return 2
        res_add = run_git(root, ["remote", "add", remote, url])
        if res_add.returncode != 0:
            print(f"Fehler: 'git remote add {remote} {url}' fehlgeschlagen: {res_add.stderr.strip()}", file=sys.stderr)
            return 2
        cfg["template_url"] = url
    else:
        if url_arg:
            cfg["template_url"] = url_arg
        elif not cfg.get("template_url"):
            res_url = run_git(root, ["remote", "get-url", remote])
            if res_url.returncode == 0:
                cfg["template_url"] = res_url.stdout.strip()

    res_fetch = run_git(root, ["fetch", remote])
    if res_fetch.returncode != 0:
        print(f"Fehler: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}", file=sys.stderr)
        return 2

    if base_arg:
        res_verify = run_git(root, ["rev-parse", "--verify", base_arg])
        if res_verify.returncode != 0:
            print(f"Fehler: --base {base_arg} ist kein gueltiger Commit.", file=sys.stderr)
            return 2
        base_full = res_verify.stdout.strip()
    else:
        res_mb = run_git(root, ["merge-base", "HEAD", f"{remote}/{branch}"])
        if res_mb.returncode != 0:
            print(
                f"Fehler: kein gemeinsamer Vorfahr zwischen HEAD und {remote}/{branch} gefunden. Entweder "
                "--base <HASH> angeben, oder sicherstellen, dass dieses Projekt per "
                "'git clone <Template-URL> <projekt>' + 'git remote rename origin template' angelegt wurde "
                "(gemeinsame Historie mit dem Template).",
                file=sys.stderr,
            )
            return 2
        base_full = res_mb.stdout.strip()

    cfg["base_commit"] = base_full
    _apply_set_pairs(cfg, set_pairs)

    save_template_json(root, cfg, path)
    print_status(root, cfg)
    return 0


def _apply_set_pairs(cfg: dict, set_pairs) -> None:
    values = cfg.setdefault("values", {})
    for pair in set_pairs or []:
        if "=" not in pair:
            print(f"Warnung: --set {pair} ignoriert (erwartet KEY=WERT).", file=sys.stderr)
            continue
        key, value = pair.split("=", 1)
        values[key.strip()] = value


def cmd_set(root: Path, cfg: dict, path: Path, set_pairs) -> int:
    if not set_pairs:
        print("Fehler: --set benoetigt mindestens ein KEY=WERT.", file=sys.stderr)
        return 2
    _apply_set_pairs(cfg, set_pairs)
    save_template_json(root, cfg, path)
    print("Werte gespeichert:")
    for k, v in (cfg.get("values") or {}).items():
        if v is not None:
            print(f"  {k} = {v}")
    return 0


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def cmd_check(root: Path, cfg: dict, quiet: bool) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    ref, fetch_noetig = compare_ref(root, cfg)
    if cfg.get("base_commit") is None or ref is None:
        if quiet:
            return 0
        print(f"Template-Update: nicht konfiguriert (Remote '{remote}' bzw. Branch '{branch}'/base_commit "
              "fehlt) - zuerst '--init' ausfuehren.")
        return 2

    if fetch_noetig:
        try:
            res_fetch = run_git(root, ["fetch", remote], timeout=20)
        except subprocess.TimeoutExpired:
            if quiet:
                return 0
            print(f"Template-Update: 'git fetch {remote}' hat das Zeitlimit (20s) ueberschritten.")
            return 2
        if res_fetch.returncode != 0:
            if quiet:
                return 0
            print(f"Template-Update: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}")
            return 2

    base = cfg["base_commit"]
    res_count = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
    if res_count.returncode != 0:
        if quiet:
            return 0
        print(f"Template-Update: Vergleich fehlgeschlagen ({res_count.stderr.strip()}).")
        return 2
    try:
        count = int(res_count.stdout.strip() or "0")
    except ValueError:
        count = 0

    if count == 0:
        if not quiet:
            print(f"Template-Update: aktuell (kein Unterschied zu {ref}).")
        return 0

    base_short = _short(root, base)
    head_short = _short(root, ref)

    lines = [f"Template-Update verfuegbar: {count} Commits (base {base_short} -> {head_short})", ""]
    res_log = run_git(root, ["log", "--oneline", f"{base}..{ref}"])
    if res_log.returncode == 0:
        lines.extend(res_log.stdout.splitlines()[:20])

    keep_local = cfg.get("keep_local") or []
    res_diff = run_git(root, ["diff", "--name-status", f"{base}..{ref}"])
    diff_lines_raw = res_diff.stdout.splitlines() if res_diff.returncode == 0 else []
    lines.append("")
    lines.append("Geaenderte Dateien:")
    for raw_line in diff_lines_raw[:30]:
        parts = raw_line.split("\t")
        rel_path = parts[-1] if parts else raw_line
        marker = "  (keep_local)" if matches_keep_local(rel_path, keep_local) else ""
        lines.append(raw_line + marker)

    lines.append("")
    lines.append("Einspielen: Skill /update-template bzw. python .claude/scripts/update-template.py --apply")
    print("\n".join(lines))
    return 3


# ---------------------------------------------------------------------------
# --apply / --continue
# ---------------------------------------------------------------------------


def get_unmerged_status(root: Path) -> dict:
    """path -> XY-Statuscode fuer alle unaufgeloesten (unmerged) Pfade.

    '-z' ist Pflicht: ohne das setzt `git status --porcelain` Pfade mit Leerzeichen in Anfuehrungszeichen
    ("docs/project/mit leer zeichen.md") - core.quotePath=false schaltet nur das Oktal-Escaping der Umlaute
    ab, nicht die Anfuehrungszeichen. Ein so verpackter Pfad passt auf kein keep_local-Muster und laesst
    sich nicht an git zurueckgeben; der Konflikt bliebe stumm liegen."""
    res = run_git(root, ["status", "--porcelain=v1", "-z"])
    out = {}
    if res.returncode != 0:
        return out
    records = [r for r in res.stdout.split("\0") if r]
    idx = 0
    while idx < len(records):
        record = records[idx]
        idx += 1
        if len(record) < 4:
            continue
        code = record[:2]
        rel_path = record[3:]
        # Bei Umbenennungen/Kopien folgt der alte Pfad als eigener Datensatz - ueberspringen, sonst wird er
        # als eigener Eintrag fehlgedeutet.
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            idx += 1
            continue
        if code[0] == "U" or code[1] == "U" or code in ("DD", "AA"):
            out[rel_path] = code
    return out


def _remaining_conflicts(root: Path):
    # -z wie in get_unmerged_status: keine Anfuehrungszeichen/Escapes um Sonderpfade.
    res = run_git(root, ["diff", "--name-only", "-z", "--diff-filter=U"])
    if res.returncode != 0:
        return []
    return [p for p in res.stdout.split("\0") if p.strip()]


def _list_conflicts(root: Path):
    """Alle noch offenen Konflikt-Pfade -> (sortierte Liste, Pfad->XY-Code). Vereinigung aus
    '--diff-filter=U' und 'status --porcelain=v1' (siehe get_unmerged_status) - deckt auch die Faelle ab,
    die im jeweils anderen Kommando fehlen wuerden (z.B. DD)."""
    status_map = get_unmerged_status(root)
    paths = set(status_map.keys())
    paths.update(_remaining_conflicts(root))
    return sorted(paths), status_map


def _merge_head(root: Path):
    res = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
    return res.stdout.strip() if res.returncode == 0 else None


def _find_renames(root: Path, ref_a, ref_b: str) -> dict:
    """Git-eigene Rename-Erkennung ref_a..ref_b (Default-Aufruf: base_commit..HEAD) -> {alter_pfad:
    (neuer_pfad, aehnlichkeit_als_string)}. Leer, wenn ref_a fehlt oder der Aufruf fehlschlaegt."""
    if not ref_a:
        return {}
    res = run_git(root, ["diff", "--find-renames=40%", "--name-status", ref_a, ref_b])
    if res.returncode != 0:
        return {}
    mapping = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].startswith("R"):
            continue
        mapping[parts[1]] = (parts[2], parts[0][1:])
    return mapping


def _cap_text(text: str) -> str:
    """Vergleichstext beschneiden: erste 200 Zeilen, hoechstens 20000 Zeichen. Die Zeichengrenze ist
    noetig, weil ratio() quadratisch laeuft - 200 Zeilen koennen auch 1 MB sein (generierte Dateien)."""
    return "\n".join(text.splitlines()[:200])[:20000]


def _similarity(a: str, b: str) -> float:
    """Inhaltsaehnlichkeit 0..1. quick_ratio() taugt NUR als billiger Vorfilter (obere Schranke): sie
    zaehlt gemeinsame Zeichen ohne Reihenfolge und liegt fuer zwei beliebige deutsche Markdown-Skelette
    bei 0.75-0.90, fuer zwei Zufallstexte sogar bei 0.998 - als Mass waere jede Datei die Umbenennung
    jeder anderen. Gemessen wird darum mit ratio(), und mit autojunk=False: die Heuristik haelt bei
    Zeichenvergleichen jedes haeufige Zeichen fuer "Junk" und drueckt echte Umbenennungen mit
    Nacharbeit von 0.78 auf 0.40."""
    if difflib.SequenceMatcher(None, a, b).quick_ratio() < 0.60:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _rename_fallback_scan(root: Path, rel_path: str, template_ref: str):
    """Kein Treffer per Git-Rename-Erkennung -> unter docs/ai/ nach .md-Dateien suchen, deren Inhalt (erste
    200 Zeilen) zu >= 60% mit der Template-Fassung von rel_path uebereinstimmt (SequenceMatcher, Stdlib,
    siehe _similarity). Liefert (rel_kandidat, ratio) oder None."""
    res = run_git(root, ["show", f"{template_ref}:{rel_path}"])
    if res.returncode != 0:
        return None
    template_text = _cap_text(res.stdout)
    docs_ai = root / "docs" / "ai"
    if not docs_ai.is_dir():
        return None
    own_name = Path(rel_path).name
    best = None
    for fp in sorted(docs_ai.glob("*.md")):
        if fp.name == own_name:
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ratio = _similarity(template_text, _cap_text(content))
        if ratio >= 0.60 and (best is None or ratio > best[1]):
            best = (fp.relative_to(root).as_posix(), ratio)
    return best


def _rename_candidate(root: Path, rel_path: str, rename_map: dict, merge_head):
    """(neuer_pfad, aehnlichkeit_in_prozent_oder_None) oder None - erst git-Rename-Erkennung (rename_map,
    siehe _find_renames), dann Fallback ueber Inhaltsaehnlichkeit unter docs/ai/ gegen die Template-Fassung
    (merge_head:rel_path). Nur fuer "DU"-Konflikte sinnvoll."""
    hit = rename_map.get(rel_path)
    if hit:
        neu, score = hit
        try:
            return neu, int(score)
        except ValueError:
            return neu, None
    if merge_head:
        fb = _rename_fallback_scan(root, rel_path, merge_head)
        if fb:
            return fb[0], int(round(fb[1] * 100))
    return None


def _reverse_rename(rename_map: dict, new_path: str):
    """Kehrt eine Rename-Map (alter_pfad -> (neuer_pfad, ...)) um: liefert den alten Pfad, dessen Ziel
    new_path ist, oder None."""
    for alt, (neu, _score) in rename_map.items():
        if neu == new_path:
            return alt
    return None


def _rename_pair_both_sides(rel_path: str, code: str, rename_map: dict, rename_map_theirs: dict):
    """Fuer "AU"/"UA"-Konflikte (rename/rename: beide Seiten haben dieselbe Basisdatei verschoben, aber auf
    unterschiedliche neue Pfade) -> (projekt_pfad, template_pfad) oder None, wenn die andere Seite nicht
    ueber die Git-Rename-Erkennung auffindbar ist. rename_map = base..HEAD (Projekt), rename_map_theirs =
    base..Template. rel_path ist bereits einer der beiden Zielpfade (der eigene, laut code)."""
    if code == "AU":
        alt = _reverse_rename(rename_map, rel_path)
        if alt is None:
            return None
        hit = rename_map_theirs.get(alt)
        if not hit:
            return None
        return rel_path, hit[0]
    if code == "UA":
        alt = _reverse_rename(rename_map_theirs, rel_path)
        if alt is None:
            return None
        hit = rename_map.get(alt)
        if not hit:
            return None
        return hit[0], rel_path
    return None


def _sh_quote(rel_path: str) -> str:
    """Pfad so einfassen, dass der ausgegebene git-Befehl auch mit Leerzeichen kopierbar bleibt."""
    if all(c.isalnum() or c in "._-/" for c in rel_path):
        return rel_path
    return "'" + rel_path.replace("'", "'\\''") + "'"


def _numstat_lines(root: Path, ref_a, ref_b, rel_path: str):
    """Summe added+deleted Zeilen (git diff --numstat) fuer rel_path zwischen ref_a und ref_b - oder None
    bei fehlender Ref, Fehler oder Binaerdatei ("-" statt Zahl)."""
    if not ref_a or not ref_b:
        return None
    res = run_git(root, ["diff", "--numstat", ref_a, ref_b, "--", rel_path])
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    if not out:
        # Leere Ausgabe heisst "unveraendert" (0) ODER "auf beiden Seiten gar nicht vorhanden" - letzteres
        # bei umbenannten Pfaden. Dann ist "0 Zeilen geaendert" irrefuehrend ("Template hat nichts
        # geaendert, also Projektfassung nehmen"), richtig ist "?".
        if run_git(root, ["cat-file", "-e", f"{ref_b}:{rel_path}"]).returncode != 0:
            return None
        return 0
    parts = out.splitlines()[0].split("\t")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) + int(parts[1])
    except ValueError:
        return None


def _print_unresolved(root: Path, still_open, intro: str) -> None:
    status_map = get_unmerged_status(root)
    print(intro, file=sys.stderr)
    for rel_path in still_open:
        kind = _conflict_kind_word(status_map.get(rel_path, "?"))
        print(f"  - {rel_path}  ({kind})", file=sys.stderr)
    print("Analyse je Konflikt: python .claude/scripts/update-template.py --conflicts", file=sys.stderr)


def _git_show_json(root: Path, revision: str, rel_path: str):
    """git show <revision>:<rel_path> -> geparstes JSON-Dict. revision ist ein normaler Commit/Branch-Verweis
    (z.B. der Stand vor dem Merge, oder die Vergleichs-Ref des Templates) - KEIN Merge-Stage-Index: waehrend
    eines echten Konflikts gibt es zwar zusaetzlich ":2"/":3" im Index, aber .claude/template.json mergt git
    bei reinen Listenergaenzungen an unterschiedlichen Stellen oft klaglos OHNE Konflikt (siehe Kopfkommentar/
    _resolve_template_json_merge) - dann existieren gar keine Stages, wohl aber die beiden Commits.

    Rueckgabe (dict, False) bei Erfolg, (None, False) wenn der Pfad bei dieser Revision fehlt (kein Fehler -
    z.B. "both added": vor dem Merge existierte die Datei projektseitig noch nicht), (None, True) wenn
    Inhalt vorhanden, aber kein gueltiges JSON-Objekt (echter Parse-Fehler)."""
    res = run_git(root, ["show", f"{revision}:{rel_path}"])
    if res.returncode != 0:
        return None, False
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return None, True
    if not isinstance(data, dict):
        return None, True
    return data, False


# Felder, die bei einem Konflikt auf .claude/template.json IMMER aus der Projektfassung (ours) stammen UND
# OHNE Rueckfall auf theirs, wenn ours das Feld nicht hat ("fehlt im Projekt" heisst hier "soll fehlen", nicht
# "aus dem Template nachladen") - je Feld begruendet:
#   - is_template: Sentinel des Template-Checkouts selbst (create-project.py entfernt ihn dort, wo daraus
#     ein echtes Projekt wird). Faellt er im Projekt weg, darf ein Merge ihn nicht aus dem Template
#     zurueckholen - genau das war der Review-Fund (Projekt hielt sich danach faelschlich fuer den
#     Template-Checkout).
#   - base_commit/updates: reine Projekt-Historie GEGENUEBER diesem Template - die eigene template.json des
#     Templates hat dazu keine sinnvolle Aussage (dort stehen bestenfalls null/[]). base_commit wird direkt
#     danach in _finalize ohnehin ueberschrieben, updates dort fortgeschrieben - ein Theirs-Fallback waere
#     hier zwar folgenlos, aber semantisch falsch, deshalb einheitlich behandelt.
#   - template_remote/template_branch/template_url: wo DIESES Projekt sein Template findet - eine
#     Projektentscheidung (--init/--url), keine Aussage des Templates ueber sich selbst.
# "values" ist bewusst NICHT hier drin: dort gewinnt zwar ebenfalls immer der Projektwert je Schluessel, aber
# neue Platzhalter, die nur das Template mitbringt, muessen ergaenzt werden (sonst bleiben sie in
# Zieldateien als "{{NEUER_PLATZHALTER}}" unersetzt stehen) - kein Ganzfeld-Fallback wie bei den obigen
# Feldern, siehe _merge_template_json_values().
_TEMPLATE_JSON_OURS_FIELDS = (
    "base_commit",
    "updates",
    "template_remote",
    "template_branch",
    "template_url",
    "is_template",
)


def _merge_template_json_values(ours_values, theirs_values):
    """Merged das 'values'-Dict (Platzhalterwerte) schluesselweise: ein vorhandener Projektschluessel
    gewinnt IMMER (auch wenn sein Wert null ist - bewusst noch nicht gesetzt). Schluessel, die nur das
    Template mitbringt (neuer Platzhalter seit dem letzten Update), werden mit Wert null ergaenzt, damit sie
    ueberhaupt in der Konfiguration auftauchen und im naechsten Schritt ersetzt/gemeldet werden koennen -
    ohne einen vorhandenen Projektwert zu ueberschreiben.

    Rueckgabe: (merged_dict oder None, wenn beide Seiten leer/fehlend sind; sortierte Liste der neu
    ergaenzten Schluessel)."""
    ours_values = ours_values if isinstance(ours_values, dict) else {}
    theirs_values = theirs_values if isinstance(theirs_values, dict) else {}
    if not ours_values and not theirs_values:
        return None, []
    merged = dict(ours_values)
    neu = sorted(key for key in theirs_values if key not in merged)
    for key in neu:
        merged[key] = None
    return merged, neu


def _merge_template_json_fields(ours, theirs):
    """Feldweiser Merge von .claude/template.json bei einem Merge-Konflikt (siehe Kopfkommentar).

    ours/theirs: geparste Dicts (siehe _git_show_json) oder None, wenn diese Stufe fehlt. Rueckgabe
    (merged_dict, hinweistext) oder (None, fehlertext), wenn keine Seite verwertbar ist."""
    if ours is None and theirs is None:
        return None, "keine Seite lesbar"

    merged = {}
    for key in _TEMPLATE_JSON_OURS_FIELDS:
        if ours is not None and key in ours:
            merged[key] = ours[key]
        # kein "elif theirs...": siehe Begruendung an der Konstante - fehlt das Feld im Projekt, bleibt es
        # auch nach dem Merge weg statt aus dem Template nachgeladen zu werden.

    values_merged, neu_values = _merge_template_json_values(
        (ours or {}).get("values"), (theirs or {}).get("values")
    )
    if values_merged is not None:
        merged["values"] = values_merged

    keep_local_ours = (ours or {}).get("keep_local") or []
    keep_local_theirs = (theirs or {}).get("keep_local") or []
    no_replace_ours = (ours or {}).get("no_replace") or []
    no_replace_theirs = (theirs or {}).get("no_replace") or []
    # Vereinigung, Reihenfolge: erst die Projekt-Eintraege in ihrer Reihenfolge, dann die neuen aus dem
    # Template, Duplikate raus. dict.fromkeys() haelt genau diese Reihenfolge und entfernt Duplikate.
    merged["keep_local"] = list(dict.fromkeys(list(keep_local_ours) + list(keep_local_theirs)))
    merged["no_replace"] = list(dict.fromkeys(list(no_replace_ours) + list(no_replace_theirs)))
    neu_keep_local = [p for p in keep_local_theirs if p not in keep_local_ours]
    neu_no_replace = [p for p in no_replace_theirs if p not in no_replace_ours]

    # Unbekannte Felder: Projektfassung gewinnt, nur-im-Template-vorhandene Felder werden uebernommen.
    # "values" steht bewusst mit dabei, obwohl es nicht mehr in _TEMPLATE_JSON_OURS_FIELDS steht - es ist
    # oben bereits schluesselweise gemergt (_merge_template_json_values); ohne diesen Eintrag wuerde die
    # Schleife es hier als "unbekanntes Feld" nochmal aus ours ueberschreiben und die frisch ergaenzten
    # Template-Schluessel wieder verwerfen.
    known = set(_TEMPLATE_JSON_OURS_FIELDS) | {"keep_local", "no_replace", "values"}
    for key, value in (ours or {}).items():
        if key not in known:
            merged[key] = value
    for key, value in (theirs or {}).items():
        if key not in known and key not in merged:
            merged[key] = value

    hinweis = (
        f"template.json feldweise zusammengefuehrt: keep_local +{len(neu_keep_local)}, "
        f"no_replace +{len(neu_no_replace)}"
    )
    if neu_values:
        hinweis += f", values +{len(neu_values)} neu ({', '.join(neu_values)}) - Werte pruefen/setzen"
    return merged, hinweis


def _resolve_template_json_merge(root: Path, cfg: dict, ours_ref: str, theirs_ref: str, rel_path: str):
    """Fuehrt .claude/template.json feldweise zusammen (siehe _merge_template_json_fields) - UNABHAENGIG
    davon, ob git den Pfad als Konflikt markiert hat: reine Listenergaenzungen an unterschiedlichen Stellen
    (Projekt ergaenzt keep_local, Template ergaenzt no_replace) mergt git oft klaglos automatisch, und der
    abschliessende save_template_json(cfg) in _finalize wuerde eine so automatisch gemergte Fassung sonst
    unbemerkt wieder verwerfen, weil cfg noch den Vor-Merge-Stand des Projekts traegt (siehe .templatedev.md
    Punkt 1 - genau dieser Fall blieb bisher unbemerkt liegen). ours_ref/theirs_ref: Commit vor dem Merge
    (Projekt) bzw. die Vergleichs-Ref des Templates.

    Schreibt bei Erfolg das Ergebnis in cfg (in place) UND auf die Platte, git add - das loest nebenbei auch
    einen echten Git-Konflikt auf diesem Pfad auf. Rueckgabe: Hinweistext fuer den Report, oder None, wenn
    der Pfad auf keiner Seite existiert (nichts zu tun)."""
    ours_data, ours_err = _git_show_json(root, ours_ref, rel_path)
    theirs_data, theirs_err = _git_show_json(root, theirs_ref, rel_path)

    if ours_data is None and theirs_data is None and not ours_err and not theirs_err:
        return None  # Pfad existiert auf keiner Seite - nichts zu tun

    if not ours_err and not theirs_err:
        merged, note = _merge_template_json_fields(ours_data, theirs_data)
        if merged is not None:
            cfg.clear()
            cfg.update(merged)
            save_template_json(root, cfg, root / rel_path)
            run_git(root, ["add", "--", rel_path])
            return note

    # Fallback: Parsen einer Seite fehlgeschlagen -> altes Verhalten (Projektfassung gewinnt komplett, bzw.
    # die einzige lesbare Seite, wenn die Projektfassung selbst kaputt ist).
    fallback_data = ours_data if ours_data is not None else theirs_data
    if fallback_data is not None:
        cfg.clear()
        cfg.update(fallback_data)
        save_template_json(root, cfg, root / rel_path)
        run_git(root, ["add", "--", rel_path])
    grund = "Parsen einer Seite fehlgeschlagen" if (ours_err or theirs_err) else "kein Feld-Merge moeglich"
    return f"immer Projektfassung ({grund})"


def cmd_apply(root: Path, cfg: dict, path: Path, do_commit: bool, continuing: bool) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    if not continuing:
        ref, fetch_noetig = compare_ref(root, cfg)
        if cfg.get("base_commit") is None or ref is None:
            print(f"Fehler: nicht konfiguriert (Remote '{remote}' bzw. Branch '{branch}'/base_commit fehlt) "
                  "- zuerst '--init' ausfuehren.", file=sys.stderr)
            return 2

        res_status = run_git(root, ["status", "--porcelain"])
        if res_status.stdout.strip():
            print("Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, dann erneut versuchen.", file=sys.stderr)
            return 2

        if fetch_noetig:
            res_fetch = run_git(root, ["fetch", remote])
            if res_fetch.returncode != 0:
                print(f"Fehler: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}", file=sys.stderr)
                return 2

        base = cfg.get("base_commit")
        if base:
            res_pending = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
            if res_pending.returncode == 0:
                try:
                    pending = int(res_pending.stdout.strip() or "0")
                except ValueError:
                    pending = None
                if pending == 0:
                    print(f"Template-Update: aktuell (kein Unterschied zu {ref}) - nichts zu tun.")
                    return 0

        pre_merge_head = run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
        res_merge = run_git(root, ["merge", "--no-ff", "--no-commit", ref])

        # Vor dem Aufloesen von TEMPLATE_JSON_REL feststellen, ob es UEBERHAUPT unaufgeloeste Pfade gab -
        # sonst wuerde "danach keine Konflikte mehr offen" (z.B. weil TEMPLATE_JSON_REL der einzige war und
        # gleich aufgeloest wird) faelschlich als "Merge aus anderem Grund fehlgeschlagen" gewertet.
        merge_failed_hard = res_merge.returncode != 0 and not get_unmerged_status(root)

        # Harten Merge-Fehler (nicht: offene Konflikte) SOFORT melden und abbrechen - VOR jedem Schreibzugriff
        # auf .claude/template.json. _resolve_template_json_merge() schreibt die Datei auf die Platte und
        # macht ein 'git add'; das darf bei einem Abbruch nicht passieren, sonst bleibt ein schmutziger
        # Arbeitsbaum zurueck (M .claude/template.json), der den dokumentierten Wiederholungsweg blockiert
        # (cmd_apply verlangt oben einen sauberen Arbeitsbaum) - war der Review-Fund.
        if merge_failed_hard:
            print(f"Fehler: 'git merge {ref}' fehlgeschlagen: {res_merge.stderr.strip()}", file=sys.stderr)
            return 2

        # .claude/template.json IMMER feldweise mergen - unabhaengig davon, ob git sie hier als Konflikt
        # markiert hat (siehe _resolve_template_json_merge). base_commit/updates werden ohnehin gleich
        # danach im Abschlussschritt aus dem hier gemergten cfg neu geschrieben. Das erledigt nebenbei auch
        # einen echten Git-Konflikt auf dem Pfad (git add loest ihn auf) - unten also aus den weiter zu
        # bearbeitenden Konflikten herausnehmen.
        template_json_note = _resolve_template_json_merge(root, cfg, pre_merge_head, ref, TEMPLATE_JSON_REL)
        if template_json_note:
            print(f"{TEMPLATE_JSON_REL}: {template_json_note}")

        if res_merge.returncode != 0:
            # get_unmerged_status() erst JETZT (nach _resolve_template_json_merge) neu abfragen: dessen
            # 'git add' hat einen echten Konflikt auf TEMPLATE_JSON_REL bereits aufgeloest (z.B. war es der
            # einzige Konflikt ueberhaupt - "both added" beim Bootstrap) - der Pfad taucht hier also nur
            # noch auf, falls er NICHT ueber diesen Mechanismus geloest werden konnte.
            conflicts = get_unmerged_status(root)

            keep_local = cfg.get("keep_local") or []
            merge_head = _merge_head(root)
            rename_map = _find_renames(root, cfg.get("base_commit"), "HEAD")
            auto_resolved, deleted_kept, dd_removed, du_decision = [], [], [], []
            for rel_path, code in conflicts.items():
                if code == "DD":
                    # von beiden geloescht - unstrittig, unabhaengig von keep_local: nichts zu bewahren.
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    dd_removed.append(rel_path)
                elif code == "DU":
                    # Vom Projekt geloescht, vom Template geaendert. Das Script darf das NICHT allein
                    # entscheiden, wenn die "Loeschung" in Wahrheit nur eine Umbenennung/Verschiebung ist
                    # (typisch: docs/ai/ auf eigene Dateinamen migriert) - sonst geht die Template-Aenderung
                    # unbemerkt verloren. Automatisch "geloescht belassen" nur, wenn der Pfad in keep_local
                    # steht (das Projekt hat bewusst entschieden) UND keine Umbenennung erkennbar ist.
                    kandidat = _rename_candidate(root, rel_path, rename_map, merge_head)
                    if kandidat is None and matches_keep_local(rel_path, keep_local):
                        res_rm = run_git(root, ["rm", "--", rel_path])
                        if res_rm.returncode != 0:
                            run_git(root, ["rm", "--cached", "--", rel_path])
                        deleted_kept.append(rel_path)
                    else:
                        du_decision.append(rel_path)
                elif matches_keep_local(rel_path, keep_local):
                    res_co = run_git(root, ["checkout", "--ours", "--", rel_path])
                    if res_co.returncode == 0:
                        run_git(root, ["add", "--", rel_path])
                        auto_resolved.append(rel_path)
                    # sonst: keine "ours"-Fassung vorhanden -> Konflikt bleibt offen, von Hand loesen

            if auto_resolved:
                print("keep_local automatisch uebernommen (Projektfassung gewinnt): " + ", ".join(sorted(auto_resolved)))
            if dd_removed:
                print("Von beiden geloescht (unstrittig) -> entfernt: " + ", ".join(sorted(dd_removed)))
            if deleted_kept:
                print("Vom Projekt geloescht (keep_local, bewusst), im Template geaendert -> geloescht belassen: " + ", ".join(sorted(deleted_kept)))
            if du_decision:
                print("Vom Projekt geloescht, im Template geaendert (Entscheidung noetig): " + ", ".join(sorted(du_decision)))

            still_open = _remaining_conflicts(root)
            if still_open:
                _print_unresolved(root, still_open, "Fehler: ungeloeste Konflikte - bitte manuell aufloesen und danach '--continue' ausfuehren:")
                return 4
    else:
        res_head = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
        if res_head.returncode != 0:
            print("Fehler: kein laufender Merge gefunden (MERGE_HEAD fehlt).", file=sys.stderr)
            return 2
        still_open = _remaining_conflicts(root)
        if still_open:
            _print_unresolved(root, still_open, "Fehler: noch ungeloeste Konflikte:")
            return 4

    return _finalize(root, cfg, path, do_commit)


def _finalize(root: Path, cfg: dict, path: Path, do_commit: bool) -> int:
    res_cached = run_git(root, ["diff", "--cached", "--name-only"])
    res_unstaged = run_git(root, ["diff", "--name-only"])
    touched = set()
    if res_cached.returncode == 0:
        touched.update(p for p in res_cached.stdout.splitlines() if p.strip())
    if res_unstaged.returncode == 0:
        touched.update(p for p in res_unstaged.stdout.splitlines() if p.strip())

    keep_local = cfg.get("keep_local") or []
    no_replace = cfg.get("no_replace") if isinstance(cfg.get("no_replace"), list) else list(DEFAULT_NO_REPLACE)
    values = cfg.get("values") or {}
    remaining_placeholders = []

    for rel_path in sorted(touched):
        if rel_path == TEMPLATE_JSON_REL:
            continue
        if matches_keep_local(rel_path, keep_local):
            continue
        fp = root / rel_path
        if not fp.exists() or not fp.is_file():
            continue
        try:
            raw = fp.read_bytes()
        except OSError:
            continue
        try:
            # Byteweise lesen/decodieren statt read_text(): read_text() macht per Default eine
            # Zeilenende-Uebersetzung (universal newlines, \r\n -> \n) - eine bewusst mit CRLF gepflegte
            # Datei wuerde dann beim Zurueckschreiben still auf LF umgestellt. decode() fasst \r\n als
            # gewoehnliche Zeichen im String an, die Ersetzung unten laesst sie unangetastet.
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # keine Textdatei (oder nicht lesbar) -> unangetastet lassen

        if matches_keep_local(rel_path, no_replace):
            # dokumentiert den Platzhalter selbst -> nie ersetzen, aber melden
            if "{{" in content:
                remaining_placeholders.append(rel_path + " (no_replace, Beispiele - so gewollt)")
            continue

        new_content = content
        for key, val in values.items():
            if val is None:
                continue
            new_content = new_content.replace("{{" + key + "}}", str(val))

        if new_content != content:
            try:
                fp.write_bytes(new_content.encode("utf-8"))
            except OSError:
                continue
            run_git(root, ["add", "--", rel_path])

        if "{{" in new_content:
            remaining_placeholders.append(rel_path)

    ref, _fetch_noetig = compare_ref(root, cfg)
    if ref is None:
        ref = f"{cfg.get('template_remote') or 'template'}/{cfg.get('template_branch') or 'main'}"
    res_new = run_git(root, ["rev-parse", ref])
    if res_new.returncode != 0:
        print(f"Fehler: '{ref}' nicht aufloesbar: {res_new.stderr.strip()}", file=sys.stderr)
        return 2
    new_base_full = res_new.stdout.strip()

    old_base = cfg.get("base_commit")
    commits_count = 0
    if old_base:
        res_cnt = run_git(root, ["rev-list", "--count", f"{old_base}..{new_base_full}"])
        if res_cnt.returncode == 0:
            try:
                commits_count = int(res_cnt.stdout.strip() or "0")
            except ValueError:
                commits_count = 0

    old_short = _short(root, old_base) if old_base else "?"
    new_short = _short(root, new_base_full)

    cfg["base_commit"] = new_base_full
    cfg.setdefault("updates", []).append(
        {
            "date": time.strftime("%Y-%m-%d"),
            "from": old_short,
            "to": new_short,
            "commits": commits_count,
        }
    )
    save_template_json(root, cfg, path)
    run_git(root, ["add", "--", TEMPLATE_JSON_REL])

    if remaining_placeholders:
        print("Warnung: '{{' bleibt uebrig (kein Wert in values gesetzt) - manuell pruefen:")
        for rel_path in remaining_placeholders:
            print(f"  - {rel_path}")

    if do_commit:
        res_status = run_git(root, ["status", "--porcelain"])
        if not res_status.stdout.strip():
            print("Keine Aenderungen - nichts zu committen.")
            return 0
        msg = f"chore(template): Update auf {new_short} ({commits_count} Commits)"
        res_commit = run_git(root, ["commit", "-m", msg])
        if res_commit.returncode != 0:
            print(f"Fehler: Commit fehlgeschlagen: {res_commit.stderr.strip()}", file=sys.stderr)
            return 2
        print(f"Commit erstellt: {msg}")
    else:
        print("Aenderungen sind gestaged - pruefen, dann committen.")

    return 0


# ---------------------------------------------------------------------------
# --conflicts
# ---------------------------------------------------------------------------


def cmd_conflicts(root: Path, cfg: dict) -> int:
    res_git = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if res_git.returncode != 0 or res_git.stdout.strip() != "true":
        print("Fehler: kein Git-Repo.", file=sys.stderr)
        return 2

    merge_head = _merge_head(root)
    if not merge_head:
        print("Kein laufender Merge (MERGE_HEAD fehlt) - '--conflicts' zeigt nur waehrend eines laufenden "
              "'--apply' etwas an; siehe 'git status'.")
        return 0

    paths, status_map = _list_conflicts(root)
    if not paths:
        print("Keine offenen Konflikte.")
        return 0

    base = cfg.get("base_commit")
    rename_map = _find_renames(root, base, "HEAD")
    rename_map_theirs = _find_renames(root, base, merge_head)

    lines = []
    for rel_path in paths:
        code = status_map.get(rel_path, "?")
        lines.append(rel_path)
        lines.append(f"  art:        {_conflict_art(code)}")
        lines.append(f"  regel:      {priority_label(rel_path)}")

        t_n = _numstat_lines(root, base, merge_head, rel_path)
        p_n = _numstat_lines(root, base, "HEAD", rel_path)
        lines.append(f"  template:   {t_n if t_n is not None else '?'} Zeilen geaendert (base..ref)")
        lines.append(f"  projekt:    {p_n if p_n is not None else '?'} Zeilen geaendert (base..HEAD)")

        if code == "DU":
            kandidat = _rename_candidate(root, rel_path, rename_map, merge_head)
            if kandidat:
                neu, pct = kandidat
                pct_txt = f"{pct}%" if pct is not None else "?"
                lines.append(f"  umbenannt?: {neu} (Aehnlichkeit {pct_txt})")
        elif code in ("AU", "UA"):
            # Beide Seiten haben dieselbe Basisdatei verschoben (rename/rename-Konflikt) - rel_path selbst
            # ist bereits der eine Zielpfad, gesucht wird der jeweils andere.
            paar = _rename_pair_both_sides(rel_path, code, rename_map, rename_map_theirs)
            if paar:
                projekt_pfad, template_pfad = paar
                lines.append(f"  umbenannt?: Projekt -> {projekt_pfad} | Template -> {template_pfad}")

        base_txt = base or "<base_commit fehlt>"
        q = _sh_quote(rel_path)
        befehle = [f"git show {merge_head}:{q}"]
        # Bei "DU" gibt es die Datei in HEAD nicht mehr - der Befehl wuerde nur einen git-Fehler liefern.
        if code != "DU":
            befehle.append(f"git show HEAD:{q}")
        befehle.append(f"git diff {base_txt} {merge_head} -- {q}")
        lines.append("  befehle:    " + "  |  ".join(befehle))
        lines.append("")

    lines.append("Weiter: Datei inhaltlich zusammenfuehren (Prioritaetsregel beachten), je geloestem Pfad")
    lines.append("'git add <pfad>', danach 'update-template.py --continue [--commit]'.")
    lines.append("Bei 'umbenannt?': die Template-Aenderung gehoert in die NEUE Datei - die alte bleibt")
    lines.append("geloescht (kein 'git add' auf den alten Pfad).")
    lines.append("Bei beidseitiger Umbenennung (Projekt und Template -> unterschiedliche neue Pfade) wird in")
    lines.append("den PROJEKT-Pfad zusammengefuehrt; der Template-Pfad wird entfernt (kein 'git add' darauf).")
    print("\n".join(lines).rstrip())
    return 0


# ---------------------------------------------------------------------------
# --graft
# ---------------------------------------------------------------------------


def _has_common_ancestor(root: Path, base_commit: str) -> bool:
    res = run_git(root, ["merge-base", "HEAD", base_commit])
    return res.returncode == 0 and bool(res.stdout.strip())


def cmd_graft(root: Path, cfg: dict) -> int:
    base_commit = cfg.get("base_commit")
    if not base_commit:
        print("Fehler: kein base_commit in .claude/template.json - zuerst apply-template.py bzw. --init ausfuehren.", file=sys.stderr)
        return 2

    res_status = run_git(root, ["status", "--porcelain"])
    if res_status.stdout.strip():
        print("Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, dann erneut versuchen.", file=sys.stderr)
        return 2

    res_verify = run_git(root, ["cat-file", "-e", base_commit])
    if res_verify.returncode != 0:
        print(
            f"Fehler: base_commit {base_commit} ist lokal nicht bekannt - erst 'git fetch "
            f"{cfg.get('template_remote') or 'template'}' ausfuehren.",
            file=sys.stderr,
        )
        return 2

    if _has_common_ancestor(root, base_commit):
        print(f"Bereits verknuepft: gemeinsamer Vorfahr mit {_short(root, base_commit)} existiert schon - nichts zu tun.")
        return 0

    base_short = _short(root, base_commit)
    msg = f"chore(template): Herkunft mit Template verknuepft (Basis {base_short})"
    res_merge = run_git(root, ["merge", "-s", "ours", "--allow-unrelated-histories", "--no-edit", "-m", msg, base_commit])
    if res_merge.returncode != 0:
        print(f"Fehler: 'git merge -s ours {base_commit}' fehlgeschlagen: {res_merge.stderr.strip()}", file=sys.stderr)
        return 2

    print(f"Verknuepft: Merge-Commit erstellt ({msg}). Arbeitsbaum unveraendert, --check/--apply funktionieren jetzt normal.")
    return 0


# ---------------------------------------------------------------------------
# --abort / --status
# ---------------------------------------------------------------------------


def cmd_abort(root: Path) -> int:
    res_head = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
    if res_head.returncode != 0:
        print("Kein laufender Merge gefunden - nichts zu tun.")
        return 0
    res_abort = run_git(root, ["merge", "--abort"])
    if res_abort.returncode != 0:
        print(f"Fehler: 'git merge --abort' fehlgeschlagen: {res_abort.stderr.strip()}", file=sys.stderr)
        return 2
    print("Merge abgebrochen (git merge --abort). .claude/template.json unveraendert.")
    return 0


def print_status(root: Path, cfg: dict) -> None:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    print(f"template_remote: {remote}")
    print(f"template_branch: {branch}")

    res_url = run_git(root, ["remote", "get-url", remote])
    url = res_url.stdout.strip() if res_url.returncode == 0 else (cfg.get("template_url") or "(kein Remote)")
    print(f"remote-url:      {url}")

    base = cfg.get("base_commit")
    print(f"base_commit:     {base or '(nicht gesetzt)'}")

    updates = cfg.get("updates") or []
    if updates:
        last = updates[-1]
        print(f"letztes update:  {last.get('date')} - {last.get('from')} -> {last.get('to')} ({last.get('commits')} Commits)")
    else:
        print("letztes update:  (noch keins)")

    ref_status, _f = compare_ref(root, cfg)
    if base and ref_status:
        ref = ref_status
        res_count = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
        if res_count.returncode == 0:
            print(f"ausstehend:      {res_count.stdout.strip()} Commits (lokaler Stand, ohne fetch)")
        else:
            print("ausstehend:      unbekannt (Ref nicht aufloesbar - noch nicht gefetcht?)")
    else:
        print("ausstehend:      unbekannt (nicht konfiguriert)")

    if base:
        res_cat = run_git(root, ["cat-file", "-e", base])
        if res_cat.returncode != 0:
            print("verknuepft:      unbekannt (base_commit lokal nicht bekannt - fetch fehlt)")
        elif _has_common_ancestor(root, base):
            print("verknuepft:      ja (gemeinsamer Vorfahr mit base_commit vorhanden)")
        else:
            print("verknuepft:      nein - '--graft' ausfuehren (nur fuer nachgeruestete Projekte noetig)")
    else:
        print("verknuepft:      -")

    values = cfg.get("values") or {}
    gesetzt = [k for k, v in values.items() if v is not None]
    print(f"values gesetzt:  {', '.join(gesetzt) if gesetzt else '(keine)'}")

    merge_head = _merge_head(root)
    if merge_head:
        offene, _status_map = _list_conflicts(root)
        print(f"merge:           laeuft (MERGE_HEAD {merge_head[:7]}), {len(offene)} Konflikt(e) offen "
              "- siehe '--conflicts'")
    else:
        print("merge:           kein laufender Merge")


def cmd_status(root: Path, cfg: dict) -> int:
    print_status(root, cfg)
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-template.py",
        description="Template-Updates per Git-Merge einspielen, ohne echte Werte durch Platzhalter zu ersetzen.",
    )
    parser.add_argument("--init", action="store_true", help="Remote/Basis-Commit/Werte initialisieren")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=WERT", help="Platzhalterwert setzen")
    parser.add_argument("--check", action="store_true", help="Auf Template-Updates pruefen (mit fetch)")
    parser.add_argument("--apply", action="store_true", help="Template-Update per Merge einspielen")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Nach manueller Konfliktaufloesung fortsetzen")
    parser.add_argument("--conflicts", action="store_true", help="Offene Konflikte eines laufenden Merges analysieren (schreibt nichts)")
    parser.add_argument("--abort", action="store_true", help="Laufenden Merge abbrechen")
    parser.add_argument("--status", action="store_true", help="Konfiguration/Stand anzeigen")
    parser.add_argument("--graft", action="store_true", help="Gemeinsame Historie mit base_commit herstellen (nachgeruestete Projekte)")
    parser.add_argument("--quiet", action="store_true", help="Nur bei --check: keine Ausgabe, wenn aktuell/nicht konfiguriert")
    parser.add_argument("--commit", action="store_true", help="Nur bei --apply/--continue: Merge-Commit direkt erstellen")
    parser.add_argument("--url", default=None, help="Nur bei --init: Remote-URL des Templates")
    parser.add_argument("--base", default=None, help="Nur bei --init: Basis-Commit explizit vorgeben")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = _find_root()
    cfg, path = load_template_json(root)

    if args.status:
        return cmd_status(root, cfg)
    if args.graft:
        return cmd_graft(root, cfg)
    if args.abort:
        return cmd_abort(root)
    if args.conflicts:
        return cmd_conflicts(root, cfg)
    if args.cont:
        return cmd_apply(root, cfg, path, args.commit, continuing=True)
    if args.apply:
        return cmd_apply(root, cfg, path, args.commit, continuing=False)
    if args.check:
        return cmd_check(root, cfg, args.quiet)
    if args.init:
        return cmd_init(root, cfg, path, args.url, args.base, args.set)
    if args.set:
        return cmd_set(root, cfg, path, args.set)

    parser.print_usage(sys.stderr)
    return 2


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"update-template: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
