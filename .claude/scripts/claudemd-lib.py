#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Bibliothek fuer die Textchirurgie an CLAUDE.md bei "Wartung: ein/aus": remove_maintenance_references
# entfernt beim Abschalten den Sub-Agenten-Eintrag [MAINTENANCE] und die zugehoerigen Tabellen-/Fliesstext-/
# Baum-Zeilen, add_maintenance_references stellt sie beim Einschalten aus dem Template-Stand wieder her.
# Herausgetrennt aus setup-lib.py (Backlog/.templatedev/questions.md Q4), das als duenne Fassade (Re-Export
# dieser drei Module) plus dem eigentlichen Setup-Ablauf bestehen bleibt - siehe dort. Braucht die beiden
# Text-Schreibhelfer aus files-lib.py (per importlib, wie dort - Bindestrich im Dateinamen).

import importlib.util
import re
from pathlib import Path


def _load_module(filename: str, mod_name: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_files_lib = _load_module("files-lib.py", "_claudemd_lib_files")
_read_text_preserve_newline = _files_lib._read_text_preserve_newline
_write_text_preserve_newline = _files_lib._write_text_preserve_newline


def remove_maintenance_references(root: Path) -> dict:
    """Entfernt bei Wartung 'aus' den Sub-Agenten-Eintrag [MAINTENANCE] und die '/act-run-maintenance'-Zeile aus
    CLAUDE.md (gleiche Technik wie remove_tool_files/_remove_table_row). Wird eine Stelle nicht gefunden,
    still weitermachen - das Ergebnis wird im Bericht genannt."""
    result = {"agent_zeile": False, "skill_zeile": False, "modell_zeile": False, "baum_zeile": False}
    path = root / "CLAUDE.md"
    if not path.exists():
        return result
    try:
        text, newline = _read_text_preserve_newline(path)
    except (UnicodeDecodeError, OSError):
        return result
    new_text = text

    agent_pattern = re.compile(r"^- \*\*\[MAINTENANCE\]\*\*.*\n(?:  .+\n)*", re.MULTILINE)
    if agent_pattern.search(new_text):
        new_text = agent_pattern.sub("", new_text)
        result["agent_zeile"] = True

    skill_pattern = re.compile(r"^\|\s*`/act-run-maintenance[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE)
    if skill_pattern.search(new_text):
        new_text = skill_pattern.sub("", new_text)
        result["skill_zeile"] = True

    # Zeile der Modell-Zuordnungstabelle (| `maintenance-orchestrator` | ... |)
    modell_pattern = re.compile(
        r"^\|\s*`maintenance-orchestrator`[^\n|]*\|[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE
    )
    if modell_pattern.search(new_text):
        new_text = modell_pattern.sub("", new_text)
        result["modell_zeile"] = True

    # Verweise im Fliesstext und im Projektbaum, die sonst ins Leere zeigen.
    fliesstext = (
        "  `maintenance-orchestrator` prüft regelmäßig, welche Agentenläufe scriptfähig sind.\n"
    )
    if fliesstext in new_text:
        new_text = new_text.replace(fliesstext, "")
        result["baum_zeile"] = True
    baum = "│   │                            # maintenance-orchestrator (optional)\n"
    if baum in new_text:
        new_text = new_text.replace(baum, "")
        result["baum_zeile"] = True
    new_text = new_text.replace(
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver,\n",
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver\n",
    )
    new_text = new_text.replace(
        "│   ├── maintenance/              # optional: Status/Intervalle + Runner für wiederkehrende Wartung\n",
        "",
    )
    new_text = new_text.replace(
        "│   │                            # maintenance-check.py (Fälligkeit der Wartung, SessionStart-Hook)\n",
        "",
    )
    new_text = new_text.replace(
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # run-maintenance, update-template, commit\n",
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # update-template, commit\n",
    )

    if new_text != text:
        _write_text_preserve_newline(path, new_text, newline)
    return result


def add_maintenance_references(root: Path, vorlage_text: str) -> dict:
    """Gegenstueck zu remove_maintenance_references: stellt bei Wartung 'ein' die Stellen in CLAUDE.md
    wieder her, die dort entfernt werden. Der wiederhergestellte Text kommt aus `vorlage_text` (CLAUDE.md-
    Stand des Template-Remotes, Platzhalter bereits ersetzt - siehe sync-config.py) statt aus einer
    zweiten, hartkodierten Kopie hier im Script, damit die Fassung nicht auseinanderlaeuft, sobald sich
    CLAUDE.md im Template weiterentwickelt. Fundstellen werden mit denselben Text-/Regex-Stuecken gesucht
    wie beim Entfernen; eingefuegt wird vor der Zeile, die im Vorlagentext unmittelbar folgt (Fallback:
    hinter der davorstehenden Zeile). Ist eine Stelle lokal schon vorhanden, passiert nichts (idempotent).
    Kennt der Vorlagentext eine Stelle selbst nicht (z.B. CLAUDE.md hat sich seither anders formuliert),
    bleibt sie unangetastet statt geraten zu werden."""
    result = {"agent_zeile": False, "skill_zeile": False, "modell_zeile": False, "baum_zeile": False}
    path = root / "CLAUDE.md"
    if not path.exists() or not vorlage_text:
        return result
    try:
        text, newline = _read_text_preserve_newline(path)
    except (UnicodeDecodeError, OSError):
        return result
    new_text = text

    def restore_pattern(pattern) -> bool:
        """Block per `pattern` in new_text suchen; fehlt er, aus vorlage_text holen und an der Stelle
        einfuegen, an der er dort steht. Als Anker dient die Zeile davor/danach, aber nur wenn sie in
        new_text genau einmal vorkommt und nicht bloss eine leere Zeile ist - sonst koennte replace()
        die falsche (erste) Fundstelle im Dokument treffen. True = danach vorhanden (schon da oder neu
        eingefuegt)."""
        nonlocal new_text
        if pattern.search(new_text):
            return True
        match = pattern.search(vorlage_text)
        if not match:
            return False
        block = match.group(0)
        rest = vorlage_text[match.end():]
        next_line_m = re.match(r"[^\n]*\n", rest)
        next_line = next_line_m.group(0) if next_line_m else None
        if next_line and next_line.strip() and new_text.count(next_line) == 1:
            new_text = new_text.replace(next_line, block + next_line, 1)
            return True
        before = vorlage_text[:match.start()]
        prev_line_m = re.search(r"[^\n]*\n$", before)
        prev_line = prev_line_m.group(0) if prev_line_m else None
        if prev_line and prev_line.strip() and new_text.count(prev_line) == 1:
            new_text = new_text.replace(prev_line, prev_line + block, 1)
            return True
        return False

    def restore_literal(before: str, after: str) -> bool:
        """Fuer Zeilen, die remove_maintenance_references per new_text.replace(before, after) veraendert
        oder komplett geloescht hat (after == ""): stellt `before` wieder her - aber nur, wenn der
        Vorlagentext `before` tatsaechlich noch so enthaelt (sonst kennt die Vorlage die Stelle in dieser
        Form nicht mehr, z.B. weil CLAUDE.md seither umformuliert wurde - dann lieber nichts anfassen)."""
        nonlocal new_text
        if before in new_text:
            return True
        if before not in vorlage_text:
            return False
        if after and new_text.count(after) == 1:
            new_text = new_text.replace(after, before, 1)
            return True
        if after == "":
            return restore_pattern(re.compile(re.escape(before)))
        return False

    agent_pattern = re.compile(r"^- \*\*\[MAINTENANCE\]\*\*.*\n(?:  .+\n)*", re.MULTILINE)
    result["agent_zeile"] = restore_pattern(agent_pattern)

    skill_pattern = re.compile(r"^\|\s*`/act-run-maintenance[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE)
    result["skill_zeile"] = restore_pattern(skill_pattern)

    modell_pattern = re.compile(
        r"^\|\s*`maintenance-orchestrator`[^\n|]*\|[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE
    )
    result["modell_zeile"] = restore_pattern(modell_pattern)

    # Fliesstext- und Projektbaum-Zeilen: dieselben Textstuecke wie in remove_maintenance_references.
    # Dort setzen nur die ersten beiden (fliesstext/baum) das Flag "baum_zeile" - die anderen vier werden
    # zwar ebenfalls entfernt/veraendert, aber ohne eigenes Flag. Hier symmetrisch: alle sechs werden
    # versucht wiederherzustellen, das Flag spiegelt aber nur fliesstext/baum (wie beim Entfernen).
    fliesstext = "  `maintenance-orchestrator` prüft regelmäßig, welche Agentenläufe scriptfähig sind.\n"
    baum = "│   │                            # maintenance-orchestrator (optional)\n"
    agents_mit_komma = (
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver,\n"
    )
    agents_ohne_komma = (
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver\n"
    )
    maintenance_ordner = (
        "│   ├── maintenance/              # optional: Status/Intervalle + Runner für wiederkehrende Wartung\n"
    )
    maintenance_check = (
        "│   │                            # maintenance-check.py (Fälligkeit der Wartung, SessionStart-Hook)\n"
    )
    skills_mit_wartung = (
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # run-maintenance, update-template, commit\n"
    )
    skills_ohne_wartung = (
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # update-template, commit\n"
    )

    fliesstext_ok = restore_literal(fliesstext, "")
    baum_ok = restore_literal(baum, "")
    restore_literal(agents_mit_komma, agents_ohne_komma)
    restore_literal(maintenance_ordner, "")
    restore_literal(maintenance_check, "")
    restore_literal(skills_mit_wartung, skills_ohne_wartung)
    result["baum_zeile"] = fliesstext_ok or baum_ok

    if new_text != text:
        _write_text_preserve_newline(path, new_text, newline)
    return result
