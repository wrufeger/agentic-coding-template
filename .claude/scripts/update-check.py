#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Erinnert bei Sitzungsstart daran, dass ein Template-Update verfuegbar waere - Pendant zu
#        feedback-check.py (dort steht der ausfuehrlichere Kopfkommentar-Stil, hier nur das, was anders ist).
#        BEWUSST EIGENSTAENDIG, aus demselben Grund wie dort: Ein abgeschaltetes Feature darf seinen eigenen
#        Hook nicht mitreissen.
#
#        Zwei Schalter in AI-CONFIG.md, dieselbe Aufteilung wie bei Feedback/Feedback-Takt:
#          - "Template-Updates": manuell (Default) | automatisch. "automatisch" heisst AUSDRUECKLICH NICHT
#            automatisch einspielen, sondern: bei Gelegenheit (hoechstens einmal je Kalendertag) im
#            Hintergrund per 'git fetch' pruefen, ob der Template-Remote neue Commits hat. Eingespielt wird
#            weiterhin ausschliesslich von Hand ueber /act-update-template. Bei "manuell" tut dieses Script
#            nichts ausser dem, was der ohnehin laufende SessionStart-Hook 'update-template.py --check --quiet'
#            schon leistet (Vergleich gegen den lokal bekannten Stand, ohne Netz).
#          - "Template-Update-Erinnerung": taeglich | woechentlich (Default) | monatlich | sitzungsstart |
#            manuell. Steuert NUR, wie oft ein bereits festgestellter Rueckstand gemeldet wird - nicht, ob
#            geprueft wird (das regelt "Template-Updates" allein). "sitzungsstart" meldet bei jedem Start,
#            solange ein Rueckstand besteht; "manuell" meldet nie (die Datei bleibt trotzdem gepflegt).
#
#        Findet die Pruefung neue Commits, schreibt dieses Script `available-template-update.md` im
#        Repo-Root (gitignored, fluechtiger Zustand): Kopfzeile mit Pruefdatum und Abstand (Anzahl Commits,
#        Kurz-Hashes von/bis), darunter die Betreffzeilen nach ihrem Conventional-Commit-Praefix gruppiert,
#        hoechstens 40 Zeilen (Rest als "... und N weitere"). Ohne Rueckstand wird eine vorhandene Datei
#        wieder entfernt. Fetch/Vergleich laufen ueber update-template.py (run_git/compare_ref/_short) statt
#        eine zweite git-Anbindung zu schreiben; das Lesen/Schreiben von AI-CONFIG.md und .claude/template.json
#        laeuft ueber die generischen Helfer aus feedback.py (_config_wert/_config_setzen/_template_json/
#        _template_json_schreiben) - beide Module bringen genau das schon mit, eine zweite Normalisierung
#        waere nur eine Fehlerquelle mehr.
#
#        Der Hook erinnert nur, er fragt nie - eine faellige Erinnerung nennt trotzdem drei Wege (ansehen und
#        einspielen, verschieben/Takt aendern, nicht mehr erinnern), damit {{AUFTRAGGEBER}} in einer Zeile
#        antworten kann. Ein Verschieben (--postpone) traegt "reminder_paused_until" in den
#        "template_updates"-Block von .claude/template.json ein - solange dieses Datum in der Zukunft liegt,
#        bleibt der Hook still. Er schreibt sonst nichts ausser diesem eigenen Block.
#
# Aufruf:
#   python .claude/scripts/update-check.py            (SessionStart-Hook)
#       Bei "Template-Updates: automatisch": hoechstens einmal je Kalendertag ein 'git fetch' des
#       Template-Remotes; aktualisiert/entfernt danach available-template-update.md. Meldet anschliessend,
#       wenn nach "Template-Update-Erinnerung" faellig. Bei "manuell": keine Aktion. Exit immer 0 - ein Hook,
#       der die Sitzung stoert, waere schlimmer als eine verpasste Erinnerung.
#   python .claude/scripts/update-check.py --status
#       Zeigt Takt, letzte Pruefung, Pausierung, ob ein Rueckstand vorliegt, faellig ja/nein. Rein lesend -
#       schreibt nichts, loest auch keinen Fetch aus.
#   python .claude/scripts/update-check.py --postpone <Tage>  (Alias: --verschieben)
#       Pausiert die Erinnerung (nicht die Pruefung selbst) um die angegebene Anzahl Tage. Option b der
#       faelligen Erinnerung.
#   python .claude/scripts/update-check.py --cadence <täglich|wöchentlich|monatlich|sitzungsstart|manuell>
#       Setzt nur "Template-Update-Erinnerung" in AI-CONFIG.md (ae-Schreibweisen und Englisch als Alias,
#       Alias fuer die Option selbst: --takt). Option c der faelligen Erinnerung ist stattdessen
#       `--cadence manuell` (siehe Meldungstext).
#
# Ausgabeformat: ein bis drei Zeilen Klartext oder nichts. Exit immer 0.

import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

FETCH_TIMEOUT_S = 8  # kurz und bewusst - ein Rechner ohne Netz darf nicht spuerbar haengen
# Mindestabstand je Erinnerungstakt in Tagen. "sitzungsstart" und "manuell" haben keinen Abstand (gesondert
# behandelt, siehe _erinnerung_faellig) - deshalb hier bewusst nicht aufgefuehrt.
ERINNERUNG_TAGE = {"täglich": 1, "wöchentlich": 7, "monatlich": 30}
# ae-Schreibweisen UND die englischen --cadence-Werte (Alias, siehe --cadence/--takt) bleiben gueltig -
# gespeichert wird vorerst weiter der heutige deutsche Wert (Umstellung ist ein spaeterer Auftrag).
ERINNERUNG_ALIAS = {
    "taeglich": "täglich", "woechentlich": "wöchentlich",
    "daily": "täglich", "weekly": "wöchentlich", "monthly": "monatlich",
    "sessionstart": "sitzungsstart", "manual": "manuell",
}
ERINNERUNG_GUELTIG = ("täglich", "wöchentlich", "monatlich", "sitzungsstart", "manuell")
AVAILABLE_REL = "available-template-update.md"
MAX_ZEILEN = 40


def _root() -> Path:
    import os
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    hier = Path(__file__).resolve().parent
    for kandidat in (hier.parent.parent, hier.parent, hier):
        if (kandidat / "AGENTS.md").exists():
            return kandidat
    return Path.cwd().resolve()


def _lade_modul(root: Path, dateiname: str, modulname: str):
    """Gemeinsamer Lader fuer feedback.py/update-template.py per importlib (Bindestriche im Dateinamen
    verbieten ein normales `import`, gleiches Muster wie in feedback-check.py/sync-config.py). None, wenn die
    Datei fehlt oder sich nicht laden laesst - ein kaputtes/fehlendes Nachbar-Script darf diesen Hook nie
    aufhalten."""
    import importlib.util
    pfad = root / ".claude" / "scripts" / dateiname
    if not pfad.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(modulname, pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


# Dieselbe Umbenennung (Block B27/T8) wie im feedback-Block von feedback.py:_feedback_block() - hier fuer den
# eigenen "template_updates"-Block. Alter Schluessel wird auf den neuen umgehaengt, ein bereits vorhandener
# neuer Schluessel hat Vorrang; ein nachfolgender Schreibvorgang speichert dadurch nur noch die neue Form.
_BLOCK_KEY_ALIAS = {"erinnerung_pausiert_bis": "reminder_paused_until", "letzte_erinnerung": "last_reminder"}


def _block(tj: dict) -> dict:
    b = tj.get("template_updates")
    b = b if isinstance(b, dict) else {}
    b = dict(b)
    for alt, neu in _BLOCK_KEY_ALIAS.items():
        if alt in b:
            wert = b.pop(alt)
            if neu not in b:
                b[neu] = wert
    return b


def _heute() -> str:
    return time.strftime("%Y-%m-%d")


def _pausiert_bis(block: dict) -> str:
    bis = str(block.get("reminder_paused_until") or "").strip()
    return bis if bis and bis > _heute() else ""


_PREFIX_RE = re.compile(r"^([A-Za-z]+)(\([^)]*\))?!?:\s*(.+)$")


def _gruppieren(zeilen):
    """zeilen: 'hash Betreff'. Gruppiert die Betreffzeilen nach ihrem Conventional-Commit-Praefix
    (feat/fix/docs/chore/...), Zeilen ohne erkennbares Praefix landen unter 'sonstige'. Rueckgabe: dict
    praefix -> [betreff, ...] in der Reihenfolge von `git log` (neueste zuerst)."""
    gruppen = {}
    for zeile in zeilen:
        _hash, _, betreff = zeile.partition(" ")
        betreff = betreff.strip()
        if not betreff:
            continue
        m = _PREFIX_RE.match(betreff)
        praefix = m.group(1).lower() if m else "sonstige"
        text = m.group(3) if m else betreff
        gruppen.setdefault(praefix, []).append(text)
    return gruppen


def _datei_schreiben(root: Path, anzahl: int, von: str, bis: str, zeilen) -> None:
    gruppen = _gruppieren(zeilen)
    inhalt = [
        f"# Verfuegbares Template-Update (geprueft am {_heute()})",
        "",
        f"{anzahl} Commit(s) im Template seit dem zuletzt eingespielten Stand ({von} -> {bis}).",
        "",
    ]
    gezeigt, rest = 0, 0
    for praefix in sorted(gruppen):
        eintraege = gruppen[praefix]
        block_zeilen = []
        for betreff in eintraege:
            if gezeigt >= MAX_ZEILEN:
                rest += 1
                continue
            block_zeilen.append(f"- {betreff}")
            gezeigt += 1
        if block_zeilen:
            inhalt.append(f"## {praefix}")
            inhalt.extend(block_zeilen)
            inhalt.append("")
    if rest:
        inhalt.append(f"… und {rest} weitere")
        inhalt.append("")
    inhalt.append("Ansehen und einspielen: `/act-update-template`.")
    (root / AVAILABLE_REL).write_text("\n".join(inhalt) + "\n", encoding="utf-8")


def _neuerungen_pruefen(root: Path, tj: dict, tu):
    """Fetcht bei Bedarf und ermittelt den Rueckstand gegenueber dem Template-Remote. Gibt
    (anzahl, von_kurz, bis_kurz, log_zeilen) zurueck; bei Fehlern/ohne Netz/ohne Konfiguration (0, None, None,
    []) - ein fehlgeschlagener Fetch ist kein Fehler dieses Scripts, sondern schlicht "kein Netz da"."""
    ref, fetch_noetig = tu.compare_ref(root, tj)
    if tj.get("base_commit") is None or ref is None:
        return 0, None, None, []
    if fetch_noetig:
        remote = tj.get("template_remote") or "template"
        try:
            res_fetch = tu.run_git(root, ["fetch", remote], timeout=FETCH_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return 0, None, None, []
        if res_fetch.returncode != 0:
            return 0, None, None, []
    base = tj["base_commit"]
    res_count = tu.run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
    if res_count.returncode != 0:
        return 0, None, None, []
    try:
        anzahl = int(res_count.stdout.strip() or "0")
    except ValueError:
        anzahl = 0
    if anzahl == 0:
        return 0, None, None, []
    res_log = tu.run_git(root, ["log", "--format=%h %s", f"{base}..{ref}"])
    zeilen = res_log.stdout.splitlines() if res_log.returncode == 0 else []
    return anzahl, tu._short(root, base), tu._short(root, ref), zeilen


def _erinnerung_faellig(takt: str, letzte_erinnerung: str, pausiert_bis: str) -> bool:
    if takt == "manuell" or pausiert_bis:
        return False
    if takt == "sitzungsstart":
        return True
    tage = ERINNERUNG_TAGE.get(takt)
    if tage is None:
        return False
    letzte = (letzte_erinnerung or "")[:10]
    if not letzte:
        return True
    try:
        verstrichen = (date.fromisoformat(_heute()) - date.fromisoformat(letzte)).days
    except ValueError:
        return True
    return verstrichen >= tage


def main() -> int:
    root = _root()
    argv = sys.argv[1:]
    ist_status = "--status" in argv

    fb = _lade_modul(root, "feedback.py", "_upd_check_fb")
    tu = _lade_modul(root, "update-template.py", "_upd_check_tu")
    if fb is None or tu is None:
        return 0

    # Eigenes argv-Parsing (kein argparse) - erkennt Haupt- (englisch) und Alias-Form (deutsch) gleichermassen.
    takt_flag = next((f for f in ("--cadence", "--takt") if f in argv), None)
    if takt_flag:
        try:
            wert = argv[argv.index(takt_flag) + 1].strip().lower()
        except IndexError:
            wert = ""
        wert = ERINNERUNG_ALIAS.get(wert, wert)
        if wert not in ERINNERUNG_GUELTIG:
            print(f"Fehler: --cadence muss eines von {', '.join(ERINNERUNG_GUELTIG)} sein.", file=sys.stderr)
            return 2
        if not fb._config_setzen(root, "Template-Update-Erinnerung", wert):
            print("Fehler: Zeile 'Template-Update-Erinnerung' in AI-CONFIG.md nicht gefunden - bitte dort "
                  "von Hand setzen.", file=sys.stderr)
            return 2
        print(f"AI-CONFIG.md: Template-Update-Erinnerung = {wert}")
        return 0

    postpone_flag = next((f for f in ("--postpone", "--verschieben") if f in argv), None)
    if postpone_flag:
        try:
            tage = int(argv[argv.index(postpone_flag) + 1])
        except (IndexError, ValueError):
            tage = 0
        if tage <= 0:
            print("Fehler: --postpone braucht eine positive Anzahl Tage.", file=sys.stderr)
            return 2
        try:
            tj = fb._template_json(root)
            block = _block(tj)
            bis = time.strftime("%Y-%m-%d", time.localtime(time.time() + tage * 86400))
            block["reminder_paused_until"] = bis
            block.pop("last_reminder", None)
            tj["template_updates"] = block
            fb._template_json_schreiben(root, tj)
        except Exception as exc:  # noqa: BLE001
            print(f"Fehler: konnte nicht schreiben ({exc}).", file=sys.stderr)
            return 2
        print(f"Erinnerung pausiert bis {bis} ({tage} Tag/e).")
        return 0

    try:
        tj = fb._template_json(root)
        if tj.get("is_template") is True:
            return 0
        modus = fb._config_wert(root, "Template-Updates", "manuell", {})
        takt = fb._config_wert(root, "Template-Update-Erinnerung", "wöchentlich", ERINNERUNG_ALIAS)
        block = _block(tj)
        pausiert_bis = _pausiert_bis(block)
        letzte_pruefung = block.get("letzte_pruefung") or ""
    except Exception:  # noqa: BLE001 - nie die Sitzung aufhalten
        return 0

    verfuegbar_datei = root / AVAILABLE_REL

    if modus == "automatisch" and not ist_status and (letzte_pruefung or "")[:10] != _heute():
        try:
            anzahl, von, bis, zeilen = _neuerungen_pruefen(root, tj, tu)
            block["letzte_pruefung"] = _heute()
            if anzahl:
                _datei_schreiben(root, anzahl, von, bis, zeilen)
            elif verfuegbar_datei.exists():
                verfuegbar_datei.unlink()
            tj["template_updates"] = block
            fb._template_json_schreiben(root, tj)
        except Exception:  # noqa: BLE001 - ein fehlgeschlagener Fetch/Schreibversuch darf die Sitzung nie stoeren
            pass

    rueckstand = modus == "automatisch" and verfuegbar_datei.exists()
    faellig = rueckstand and _erinnerung_faellig(takt, block.get("last_reminder") or "", pausiert_bis)

    if ist_status:
        print(f"Template-Updates: {modus}, Erinnerung: {takt}")
        print(f"Letzte Pruefung: {letzte_pruefung or 'nie'}")
        if pausiert_bis:
            print(f"Pausiert bis: {pausiert_bis}")
        print(f"Rueckstand bekannt: {'ja' if rueckstand else 'nein'}"
              + (f" ({AVAILABLE_REL})" if verfuegbar_datei.exists() else ""))
        print("Erinnerung faellig: " + ("ja" if faellig else "nein"))
        return 0

    if faellig:
        block["last_reminder"] = _heute()
        tj["template_updates"] = block
        try:
            fb._template_json_schreiben(root, tj)
        except Exception:  # noqa: BLE001
            pass
        print(f"Ein Template-Update ist verfuegbar (siehe {AVAILABLE_REL}).")
        print("a) ansehen und einspielen: /act-update-template   b) verschieben (Tage) oder Takt aendern   "
              "c) nicht mehr erinnern: update-check.py --cadence manuell")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
