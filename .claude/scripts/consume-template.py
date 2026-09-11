#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Weg 2 ("Bestehendes Projekt nachruesten") aus README.md/AGENTS.md umsetzen - kopiert die
#        Agentic-Coding-Grundausstattung dieses Template-Checkouts in ein bestehendes, fremdes Repo, ohne
#        dort etwas zu ueberschreiben. Legt im Ziel `.claude/template.json` an (Remote/Basis-Commit des
#        Templates, Werte noch leer) und richtet den Git-Remote "template" ein, damit
#        `template-update.py --graft` danach eine gemeinsame Historie herstellen kann. Laeuft AUS DIESEM
#        TEMPLATE-CHECKOUT HERAUS (nicht im Zielrepo). Reine Python-Stdlib, kein Paket noetig. Siehe
#        `.claude/skills/consume-template/SKILL.md`, `docs/ai/checklists.md` § "Projekt nachruesten".
#
# Aufruf:
#   python .claude/scripts/consume-template.py --target <ziel-repo> [--dry-run]
#       --dry-run (optional): nur anzeigen, was kopiert/uebersprungen wuerde, nichts schreiben.
#       ohne --dry-run: kopiert tatsaechlich, schreibt .claude/template.json im Ziel, legt bei Bedarf den
#       Remote "template" an und fetcht ihn.
#
# Kopiert (nie ueberschrieben - vorhandene Zieldateien werden uebersprungen und am Ende gelistet):
#   AGENTS.md, CLAUDE.md, GEMINI.md, .aider.conf.yml, .cursor/, .github/copilot-instructions.md,
#   .claude/ (komplett AUSSER .claude/settings.local.json), docs/ai/ (alle), docs/project/ (alle Skelette
#   inkl. incidents/), docs/README.md, CONFIG.md, .editorconfig, .gitattributes, renovate.json,
#   .mcp.json.example, .env.example, .github/workflows/ci.yml.
# NIE kopiert: README.md (wird im Ziel meist schon existieren; eigener Abschnitt statt Ersetzung, siehe
#   Skill), .gitignore (stattdessen werden fehlende Zeilen aus dem Template-.gitignore als Vorschlag
#   ausgegeben, nie automatisch geschrieben).
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungsfehler (--target fehlt/ungueltig). Ein Fehler dieses Scripts darf nie
# mit Traceback nach aussen dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr.

import argparse
import fnmatch
import importlib.util
import os
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

COPY_ITEMS = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".aider.conf.yml",
    ".cursor",
    ".github/copilot-instructions.md",
    ".claude",
    "docs/ai",
    "docs/project",
    "docs/README.md",
    "CONFIG.md",
    ".editorconfig",
    ".gitattributes",
    "renovate.json",
    ".mcp.json.example",
    ".env.example",
    ".github/workflows/ci.yml",
]

# Nie kopieren: lokale Secrets/Permissions und gitignorierte Laufzeit-Artefakte des Template-Checkouts
# (Wartungslogs/-berichte, Mitschnitte) - die gehoeren nicht in ein fremdes Repo.
EXCLUDE_FILES = {".claude/settings.local.json"}
EXCLUDE_GLOBS = [
    ".claude/maintenance/reports/*",
    ".claude/maintenance/*.log",
    "*/ai.log",
    "ai.log",
    "ai.log.*",
    "*.pyc",
    "*.pyo",
]


def _is_excluded(rel: str) -> bool:
    if rel in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatchcase(rel, pat) for pat in EXCLUDE_GLOBS)


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _template_root() -> Path:
    # Bewusst NICHT ueber CLAUDE_PROJECT_DIR: dieses Script laeuft aus dem Template-Checkout, das kann ein
    # anderes Verzeichnis sein als das gerade aktive Claude-Code-Projekt (das Zielrepo).
    return Path(__file__).resolve().parents[2]


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


def _load_template_update_module(template_root: Path):
    tu_path = template_root / ".claude" / "scripts" / "template-update.py"
    spec = importlib.util.spec_from_file_location("_template_update_ct", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Kopieren
# ---------------------------------------------------------------------------


def _plan_files(template_root: Path):
    """Liefert (rel_path, is_new_dir_root) fuer jede zu kopierende Datei relativ zu template_root."""
    for item in COPY_ITEMS:
        src = template_root / item
        if not src.exists():
            continue
        if src.is_dir():
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fname in filenames:
                    if fname.endswith((".pyc", ".pyo")):
                        continue
                    fp = Path(dirpath) / fname
                    rel = fp.relative_to(template_root).as_posix()
                    if _is_excluded(rel):
                        continue
                    yield rel
        else:
            rel = src.relative_to(template_root).as_posix()
            if not _is_excluded(rel):
                yield rel


def copy_into_target(template_root: Path, target_root: Path, dry_run: bool):
    copied, skipped = [], []
    for rel in _plan_files(template_root):
        src = template_root / rel
        dest = target_root / rel
        if dest.exists():
            skipped.append(rel)
            continue
        copied.append(rel)
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return sorted(copied), sorted(skipped)


def gitignore_suggestion(template_root: Path, target_root: Path):
    tmpl_gi = template_root / ".gitignore"
    if not tmpl_gi.exists():
        return []
    try:
        tmpl_lines = [l.rstrip("\n") for l in tmpl_gi.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []
    target_gi = target_root / ".gitignore"
    target_lines = set()
    if target_gi.exists():
        try:
            target_lines = {l.strip() for l in target_gi.read_text(encoding="utf-8").splitlines()}
        except OSError:
            target_lines = set()
    missing = []
    for line in tmpl_lines:
        stripped = line.strip()
        if not stripped or stripped in target_lines:
            continue
        missing.append(line)
    return missing


# ---------------------------------------------------------------------------
# template.json im Ziel
# ---------------------------------------------------------------------------


def write_target_template_json(template_root: Path, target_root: Path, dry_run: bool):
    tu = _load_template_update_module(template_root)
    cfg = tu.default_config()

    res_branch = run_git(template_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = res_branch.stdout.strip() if res_branch.returncode == 0 and res_branch.stdout.strip() else "main"
    cfg["template_branch"] = branch

    res_url = run_git(template_root, ["remote", "get-url", "origin"])
    if res_url.returncode == 0 and res_url.stdout.strip():
        cfg["template_url"] = res_url.stdout.strip()
    else:
        cfg["template_url"] = str(template_root)

    res_head = run_git(template_root, ["rev-parse", "HEAD"])
    cfg["base_commit"] = res_head.stdout.strip() if res_head.returncode == 0 else None

    if dry_run:
        return cfg

    path = target_root / tu.TEMPLATE_JSON_REL
    tu.save_template_json(target_root, cfg, path)
    return cfg


def setup_template_remote(template_root: Path, target_root: Path, template_url: str, dry_run: bool) -> str:
    res_check = run_git(target_root, ["rev-parse", "--is-inside-work-tree"])
    if res_check.returncode != 0:
        return "Ziel ist kein Git-Repo - Remote 'template' nicht angelegt."

    res_remotes = run_git(target_root, ["remote"])
    remotes = res_remotes.stdout.split() if res_remotes.returncode == 0 else []
    if "template" in remotes:
        return "Remote 'template' existiert bereits im Ziel."

    if dry_run:
        return f"wuerde Remote 'template' -> {template_url} anlegen und fetchen."

    res_add = run_git(target_root, ["remote", "add", "template", template_url])
    if res_add.returncode != 0:
        return f"Remote 'template' anlegen fehlgeschlagen: {res_add.stderr.strip()}"
    res_fetch = run_git(target_root, ["fetch", "template"], timeout=30)
    if res_fetch.returncode != 0:
        return f"Remote 'template' angelegt, 'git fetch template' fehlgeschlagen: {res_fetch.stderr.strip()}"
    return "Remote 'template' angelegt und gefetcht."


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _run(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="consume-template.py",
        description="Agentic-Coding-Grundausstattung dieses Templates in ein bestehendes Repo kopieren (Weg 2).",
    )
    parser.add_argument("--target", required=True, help="Pfad zum Ziel-Repo")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    args = parser.parse_args(argv)

    template_root = _template_root()
    target_root = Path(args.target).resolve()

    if not target_root.exists() or not target_root.is_dir():
        print(f"Fehler: --target {target_root} existiert nicht oder ist kein Verzeichnis.", file=sys.stderr)
        return 2

    # Das Template in sich selbst (oder in einen eigenen Unterordner) zu kopieren ueberschreibt dessen
    # .claude/template.json bzw. legt eine Kopie im Checkout ab - beides nie gewollt.
    if target_root == template_root or template_root in target_root.parents:
        print(
            f"Fehler: --target {target_root} liegt im Template-Checkout ({template_root}) - Ziel muss ein "
            "anderes Repo sein.",
            file=sys.stderr,
        )
        return 2

    copied, skipped = copy_into_target(template_root, target_root, args.dry_run)
    gi_suggestion = gitignore_suggestion(template_root, target_root)
    cfg = write_target_template_json(template_root, target_root, args.dry_run)
    remote_status = setup_template_remote(template_root, target_root, cfg.get("template_url"), args.dry_run)

    lines = [f"consume-template.py {'--dry-run' if args.dry_run else '--apply'} -> {target_root}", ""]
    lines.append(f"Kopiert ({len(copied)}):")
    lines.extend(f"  {rel}" for rel in copied[:60])
    if len(copied) > 60:
        lines.append(f"  ... und {len(copied) - 60} weitere")

    lines.append("")
    lines.append(f"Uebersprungen, vorhanden im Ziel - von Hand zusammenfuehren ({len(skipped)}):")
    lines.extend(f"  {rel}" for rel in skipped)
    if not skipped:
        lines.append("  (keine)")

    lines.append("")
    if gi_suggestion:
        lines.append(".gitignore - fehlende Zeilen aus dem Template (Vorschlag, nicht automatisch uebernommen):")
        lines.extend(f"  {l}" for l in gi_suggestion)
    else:
        lines.append(".gitignore: keine fehlenden Zeilen bzw. Ziel-.gitignore deckt das Template ab.")

    lines.append("")
    lines.append(f".claude/template.json: base_commit={cfg.get('base_commit')}, template_url={cfg.get('template_url')}")
    lines.append(f"Remote 'template': {remote_status}")

    lines.append("")
    lines.append("Naechste Schritte: im Zielrepo Skill /consume-template ausfuehren (CONFIG.md befuellen, "
                  "docs/project mit dem IST-Zustand befuellen, danach template-update.py --graft).")

    print("\n".join(lines))
    return 0


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"consume-template: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
