#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Template-Updates in ein aus diesem Template abgeleitetes Projekt per Git-Merge einspielen, ohne
#        dass echte Werte wieder durch Platzhalter (`{{PROJEKTNAME}}` usw.) ersetzt werden. Verwaltet dazu
#        `.claude/template.json` (Remote/Branch des Templates, zuletzt eingespielter Basis-Commit, die
#        eingesetzten Platzhalterwerte, Dateien/Ordner, deren Projektfassung bei Konflikten immer gewinnt,
#        Update-Historie). Siehe AGENTS.md § "Template-Herkunft und Updates", CLAUDE.md § 2 (Skill
#        `/template-update`), docs/ai/checklists.md § "Template-Update". Reine Python-Stdlib, kein Paket
#        noetig.
#
# Aufruf:
#   python .claude/scripts/template-update.py --init [--url URL] [--base HASH] [--set KEY=WERT ...]
#       Legt Remote "template" an (falls noetig), ermittelt/uebernimmt den Basis-Commit, speichert Werte.
#   python .claude/scripts/template-update.py --set KEY=WERT [--set KEY=WERT ...]
#       Nur Platzhalterwerte schreiben (ohne Remote/Basis-Commit anzufassen).
#   python .claude/scripts/template-update.py --check [--quiet]
#       Prueft, ob das Template neuer ist als der gespeicherte Basis-Commit (mit fetch, Timeout 20s).
#       Exit 0 = aktuell/nicht konfiguriert (bei --quiet), 2 = nicht konfiguriert/Netzwerkfehler (ohne
#       --quiet), 3 = Update verfuegbar (Ausgabe: Commits, geaenderte Dateien, keep_local-Markierung).
#   python .claude/scripts/template-update.py --apply [--commit]
#       Mergt template/<branch> in den Arbeitsbaum (git merge --no-ff --no-commit). Konflikte in
#       .claude/template.json werden IMMER zugunsten der Projektfassung geloest (auch "both added" beim
#       Bootstrap, siehe unten) - unabhaengig von keep_local; Konflikte in keep_local-Pfaden ebenso
#       automatisch zugunsten der Projektfassung, vom Projekt geloeschte/vom Template geaenderte Dateien
#       bleiben geloescht; uebrige Konflikte muessen von Hand geloest werden (danach --continue). Ohne
#       Konflikte bzw. nach deren Aufloesung: Platzhalter in den vom Merge beruehrten Textdateien (ausser
#       keep_local und no_replace) ersetzen, base_commit/updates fortschreiben, git add.
#   python .claude/scripts/template-update.py --continue [--commit]
#       Nach manueller Konfliktaufloesung: prueft, dass keine Konflikte mehr offen sind, fuehrt den
#       Abschlussschritt von --apply aus.
#   python .claude/scripts/template-update.py --abort
#       Bricht einen laufenden Merge ab (git merge --abort); .claude/template.json bleibt unveraendert.
#   python .claude/scripts/template-update.py --status
#       Zeigt Konfiguration, Remote-URL, base_commit, letztes Update, Anzahl ausstehender Commits (ohne
#       fetch, also ggf. veralteter Stand), sowie ob eine gemeinsame Historie mit base_commit existiert
#       (graft-Status).
#   python .claude/scripts/template-update.py --graft
#       Fuer per `consume-template.py` nachgeruestete Projekte (kein gemeinsamer Vorfahr mit dem Template):
#       stellt per leerem Merge (`git merge -s ours --allow-unrelated-histories`) eine gemeinsame Historie
#       zu base_commit her, OHNE den Arbeitsbaum zu veraendern - danach funktionieren --check/--apply wie
#       bei einem per `git clone` angelegten Projekt. Voraussetzung: sauberer Arbeitsbaum, base_commit
#       gesetzt (siehe .claude/template.json), Remote vorher gefetcht (macht `consume-template.py` bzw. der
#       Skill /consume-template bereits). Existiert bereits ein gemeinsamer Vorfahr (`git merge-base HEAD
#       base_commit`), ist --graft ein No-op (Exit 0, Hinweis).
#
# --commit auf --apply/--continue erstellt den Merge-Commit direkt; ohne --commit bleiben die Aenderungen
# gestaged, damit sie vor dem Commit geprueft werden koennen.
#
# Bootstrap (bestehendes Projekt hat dieses Script noch nicht): mit
#   CLAUDE_PROJECT_DIR=<projekt> python <template-checkout>/.claude/scripts/template-update.py --init ...
#   aufrufen - die Root kommt strikt aus CLAUDE_PROJECT_DIR, das Script selbst kann ausserhalb des
#   Projekts liegen. Fehlt .claude/template.json im Projekt, wird intern mit einer leeren Default-
#   Konfiguration gearbeitet (--init legt die Datei an; --check --quiet ohne Datei ist still Exit 0).
#
# keep_local (template.json) = Projektfassung gewinnt BEI KONFLIKTEN und wird nie platzhalter-ersetzt;
# konfliktfreie Template-Aenderungen an diesen Dateien merged git ganz normal mit hinein.
# no_replace (template.json) = Dateien, die den Platzhalter selbst dokumentieren; sie werden gemergt, aber
# nie ersetzt.
#
# git laeuft immer nicht-interaktiv (GIT_TERMINAL_PROMPT=0, stdin geschlossen): ein privates Template ohne
# hinterlegten Credential-Helper meldet einen Fehler, statt im Hook auf eine Passworteingabe zu warten.
#
# Exit-Codes: 0 = ok/aktuell, 2 = Konfigurations-/Vorbedingungsfehler, 3 = Update verfuegbar (nur --check),
#             4 = Konflikte offen (nur --apply/--continue). Ein Fehler dieses Scripts darf nie mit
#             Traceback nach aussen dringen: main() laeuft komplett in try/except, Fehlermeldungen auf
#             stderr. `--check --quiet` schreibt nie auf stdout, ausser es gibt tatsaechlich ein Update.

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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
    "README.md",
    "CONFIG.md",
    ".env.example",
    ".github/workflows/ci.yml",
    ".mcp.json.example",
]

# Dateien, die den Platzhalter selbst dokumentieren (Beispielaufzaehlungen in Checklisten/Skills). Sie werden
# normal gemergt, aber NIE ersetzt - sonst macht ein Update aus "Alle Platzhalter (`{{PROJEKTNAME}}`, ...)"
# die Zeile "Alle Platzhalter (`Kundenportal`, ...)" und die Anleitung ist kaputt.
DEFAULT_NO_REPLACE = [
    ".claude/scripts/new-project.py",
    ".claude/scripts/template-update.py",
]

TEMPLATE_JSON_REL = ".claude/template.json"

_HINWEIS = (
    "Speichert die Herkunft dieses Projekts gegenueber dem Template (Remote, Basis-Commit, eingesetzte "
    "Platzhalterwerte) fuer spaetere Updates per Merge. Wird von `template-update.py --init` befuellt; "
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
        "_hinweis": cfg.get("_hinweis") or _HINWEIS,
    }
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

    if cfg.get("base_commit") is None or not _remote_exists(root, remote):
        if quiet:
            return 0
        print(f"Template-Update: nicht konfiguriert (Remote '{remote}'/base_commit fehlt) - zuerst '--init' ausfuehren.")
        return 2

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
    ref = f"{remote}/{branch}"
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
    lines.append("Einspielen: Skill /template-update bzw. python .claude/scripts/template-update.py --apply")
    print("\n".join(lines))
    return 3


# ---------------------------------------------------------------------------
# --apply / --continue
# ---------------------------------------------------------------------------


def get_unmerged_status(root: Path) -> dict:
    """path -> XY-Statuscode fuer alle unaufgeloesten (unmerged) Pfade."""
    res = run_git(root, ["status", "--porcelain=v1"])
    out = {}
    if res.returncode != 0:
        return out
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        rel_path = line[3:]
        if code[0] == "U" or code[1] == "U" or code in ("DD", "AA"):
            out[rel_path] = code
    return out


def _remaining_conflicts(root: Path):
    res = run_git(root, ["diff", "--name-only", "--diff-filter=U"])
    if res.returncode != 0:
        return []
    return [p for p in res.stdout.splitlines() if p.strip()]


def cmd_apply(root: Path, cfg: dict, path: Path, do_commit: bool, continuing: bool) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    if not continuing:
        if cfg.get("base_commit") is None or not _remote_exists(root, remote):
            print(f"Fehler: nicht konfiguriert (Remote '{remote}'/base_commit fehlt) - zuerst '--init' ausfuehren.", file=sys.stderr)
            return 2

        res_status = run_git(root, ["status", "--porcelain"])
        if res_status.stdout.strip():
            print("Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, dann erneut versuchen.", file=sys.stderr)
            return 2

        res_fetch = run_git(root, ["fetch", remote])
        if res_fetch.returncode != 0:
            print(f"Fehler: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}", file=sys.stderr)
            return 2

        ref = f"{remote}/{branch}"

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

        res_merge = run_git(root, ["merge", "--no-ff", "--no-commit", ref])
        if res_merge.returncode != 0:
            conflicts = get_unmerged_status(root)
            if not conflicts:
                print(f"Fehler: 'git merge {ref}' fehlgeschlagen: {res_merge.stderr.strip()}", file=sys.stderr)
                return 2

            keep_local = cfg.get("keep_local") or []
            auto_resolved, deleted_kept = [], []
            for rel_path, code in conflicts.items():
                if rel_path == TEMPLATE_JSON_REL:
                    # Eigene Zustandsdatei: Konflikte IMMER zugunsten der Projektfassung ("ours") loesen -
                    # unabhaengig von keep_local, auch bei "both added" (Projekt hat sie per --init
                    # angelegt, das Template bringt sie im selben Update erstmals mit). base_commit/
                    # updates werden ohnehin gleich danach im Abschlussschritt aus dem hier geladenen
                    # cfg neu geschrieben.
                    res_co = run_git(root, ["checkout", "--ours", "--", rel_path])
                    if res_co.returncode == 0:
                        run_git(root, ["add", "--", rel_path])
                    else:
                        # keine "ours"-Stufe im Index (z.B. von uns geloescht) -> Konflikt nur bereinigen
                        run_git(root, ["rm", "-f", "--cached", "--", rel_path])
                    auto_resolved.append(rel_path + " (immer Projektfassung)")
                elif matches_keep_local(rel_path, keep_local):
                    if code in ("DU", "DD"):
                        # Projektfassung = geloescht. Es gibt keine "ours"-Stufe im Index; ein blindes
                        # 'git add' wuerde hier die Template-Fassung wiederbeleben.
                        res_rm = run_git(root, ["rm", "--", rel_path])
                        if res_rm.returncode != 0:
                            run_git(root, ["rm", "--cached", "--", rel_path])
                        deleted_kept.append(rel_path)
                    else:
                        res_co = run_git(root, ["checkout", "--ours", "--", rel_path])
                        if res_co.returncode == 0:
                            run_git(root, ["add", "--", rel_path])
                            auto_resolved.append(rel_path)
                        # sonst: keine "ours"-Fassung vorhanden -> Konflikt bleibt offen, von Hand loesen
                elif code == "DU":
                    # vom Projekt geloescht, vom Template geaendert -> geloescht lassen
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    deleted_kept.append(rel_path)

            if auto_resolved:
                print("keep_local automatisch uebernommen (Projektfassung gewinnt): " + ", ".join(sorted(auto_resolved)))
            if deleted_kept:
                print("Vom Projekt geloescht, im Template geaendert -> geloescht belassen: " + ", ".join(sorted(deleted_kept)))

            still_open = _remaining_conflicts(root)
            if still_open:
                print("Fehler: ungeloeste Konflikte - bitte manuell aufloesen und danach '--continue' ausfuehren:", file=sys.stderr)
                for rel_path in still_open:
                    print(f"  - {rel_path}", file=sys.stderr)
                return 4
    else:
        res_head = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
        if res_head.returncode != 0:
            print("Fehler: kein laufender Merge gefunden (MERGE_HEAD fehlt).", file=sys.stderr)
            return 2
        still_open = _remaining_conflicts(root)
        if still_open:
            print("Fehler: noch ungeloeste Konflikte:", file=sys.stderr)
            for rel_path in still_open:
                print(f"  - {rel_path}", file=sys.stderr)
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
            content = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
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
                fp.write_text(new_content, encoding="utf-8", newline="\n")
            except OSError:
                continue
            run_git(root, ["add", "--", rel_path])

        if "{{" in new_content:
            remaining_placeholders.append(rel_path)

    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    ref = f"{remote}/{branch}"
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
# --graft
# ---------------------------------------------------------------------------


def _has_common_ancestor(root: Path, base_commit: str) -> bool:
    res = run_git(root, ["merge-base", "HEAD", base_commit])
    return res.returncode == 0 and bool(res.stdout.strip())


def cmd_graft(root: Path, cfg: dict) -> int:
    base_commit = cfg.get("base_commit")
    if not base_commit:
        print("Fehler: kein base_commit in .claude/template.json - zuerst consume-template.py bzw. --init ausfuehren.", file=sys.stderr)
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

    if base and _remote_exists(root, remote):
        ref = f"{remote}/{branch}"
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


def cmd_status(root: Path, cfg: dict) -> int:
    print_status(root, cfg)
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="template-update.py",
        description="Template-Updates per Git-Merge einspielen, ohne echte Werte durch Platzhalter zu ersetzen.",
    )
    parser.add_argument("--init", action="store_true", help="Remote/Basis-Commit/Werte initialisieren")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=WERT", help="Platzhalterwert setzen")
    parser.add_argument("--check", action="store_true", help="Auf Template-Updates pruefen (mit fetch)")
    parser.add_argument("--apply", action="store_true", help="Template-Update per Merge einspielen")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Nach manueller Konfliktaufloesung fortsetzen")
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
        print(f"template-update: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
