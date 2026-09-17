#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Erinnert bei Sitzungsstart daran, dass eine freiwillige Rueckmeldung faellig waere - und zwar in
#        einem Takt, der zum Projekt passt. Gegenstueck zu maintenance-check.py, aber BEWUSST EIGENSTAENDIG:
#        Die Wartung ist abwaehlbar (AI-CONFIG.md § Wartung), und mit ihr verschwaende ihr Hook - die
#        Rueckmeldung haette dann keinen Ausloeser mehr.
#
#        Zwei Arten von Faelligkeit, je nach Feedback-Takt (AI-CONFIG.md):
#          - jeder feste Takt ("sofort"/"stuendlich"/"taeglich"/"woechentlich"/"automatisch"): faellig nach
#            dem Mindestabstand aus TAKT_STUNDEN (feedback.py - dieselbe Tabelle, kein zweites Original).
#          - "adaptiv": misst nicht die Zeit, sondern die ARBEIT (Tage MIT Commits seit der letzten Sendung)
#            UND die REAKTION auf frühere Erinnerungen - siehe unten.
#          "manuell" (Feedback ODER Feedback-Takt) und "aus" erinnern nie. MINDESTABSTAND_H bleibt in jedem
#          Fall die harte Untergrenze, damit kein Takt oefter als einmal in zwei Tagen erinnert.
#
#        Die Schwelle fuer "adaptiv" (in Arbeitstagen) ist keine feste Zahl mehr, sondern wird aus
#        FAELLIG_TAGE (Basis) berechnet - drei Einfluesse, in dieser Reihenfolge:
#          1. Ignoriert/verschoben -> SELTENER. Zaehler im feedback-Block von .claude/template.json:
#             "erinnerungen_ohne_reaktion" (dieses Script zaehlt hoch, siehe _merker_fortschreiben - die
#             ALLERERSTE Erinnerung eines Zyklus zaehlt noch nicht, erst die naechste ohne Sendung dazwischen,
#             hoechstens ein Schritt je Kalendertag) und "verschiebungen" (feedback.py --verschieben). Je
#             Zaehlung: Schwelle *= LERN_FAKTOR_NEGATIV, gedeckelt bei SCHWELLE_MAX.
#          2. Gesendet -> HAEUFIGER. Nach jedem --send wird "sendungen_in_folge" hochgezaehlt und die beiden
#             Zaehler aus 1. auf 0 gesetzt (feedback.py:cmd_send) - eine Sendung loescht also die
#             "negative" Vorgeschichte. Je Zaehlung: Schwelle *= LERN_FAKTOR_POSITIV, Untergrenze
#             SCHWELLE_MIN.
#          3. Template-Update -> HAEUFIGER. Je Eintrag in .claude/template.json § "updates" NACH der letzten
#             Sendung sinkt die Schwelle um LERN_SCHRITT_UPDATE Arbeitstage, ebenfalls Untergrenze
#             SCHWELLE_MIN. Begruendung: Wer ein Update einspielt, hofft haeufig auf einen Fix - von dem ist
#             eine Rueckmeldung besonders wertvoll und besonders wahrscheinlich.
#          Am Ende: auf [SCHWELLE_MIN, SCHWELLE_MAX] begrenzt und auf ganze Tage gerundet. --status zeigt die
#          Rechnung als Text (siehe _adaptive_schwelle), damit ein lernender Takt keine Blackbox bleibt.
#          Diese Zaehler beschreiben die ARBEITSWEISE mit der Erinnerung selbst und sind Teil der anonymen
#          Nutzungsstatistik (Feedback-Umfang "c") - sie gehen mit, wenn dieser Umfang gewaehlt ist. Die
#          Anbindung an feedback.py:_nutzlast() ist NICHT Teil dieses Scripts, sondern eines eigenen Laufs,
#          der Umfang "c" um diese Zahlen erweitert.
#
#        Der Hook erinnert nur, er fragt nie - eine faellige Erinnerung bei Feedback-Modus "bestätigen"
#        nennt trotzdem drei Wege (ansehen+senden, verschieben/Takt aendern, nicht mehr erinnern), damit
#        {{AUFTRAGGEBER}} in einer Zeile antworten kann; die eigentliche Aktion fuehrt der Assistent im
#        Gespraech aus (siehe .claude/skills/act-feedback/SKILL.md). Ein Verschieben (feedback.py
#        --verschieben) traegt "erinnerung_pausiert_bis" in den feedback-Block von .claude/template.json ein
#        - solange dieses Datum in der Zukunft liegt, bleibt der Hook still. Er schreibt sonst nichts ausser
#        diesen eigenen Merkern - und bei "Feedback: aus" tut er sofort gar nichts.
#
# Aufruf:
#   python .claude/scripts/feedback-check.py            (SessionStart-Hook)
#       Gibt eine Erinnerung aus (bei Modus "bestätigen" mit drei Optionen a/b/c), wenn etwas faellig ist -
#       sonst nichts. Schreibt bei Takt "adaptiv" seinen eigenen Lern-Merker fort (siehe oben). Exit immer 0:
#       ein Hook, der die Sitzung stoert, waere schlimmer als eine verpasste Erinnerung.
#   python .claude/scripts/feedback-check.py --status
#       Zeigt die Rechnung dahinter (Takt, Arbeitstage/Stunden seit der letzten Sendung, bei "adaptiv" die
#       Schwelle samt Begruendung, Pause, faellig ja/nein). Rein lesend - schreibt nichts, auch keinen Merker.
#
# Ausgabeformat: ein bis drei Zeilen Klartext oder nichts. Exit immer 0.

import subprocess
import sys
import time
from pathlib import Path

FAELLIG_TAGE = 5          # Basis-Schwelle fuer Takt "adaptiv", in Arbeitstagen MIT Commits
MINDESTABSTAND_H = 48     # nie oefter erinnern, egal wie viel gearbeitet wurde - harte Untergrenze
LERN_FAKTOR_NEGATIV = 1.5 # je ignorierter Erinnerung/Verschiebung: Schwelle * diesen Faktor
LERN_FAKTOR_POSITIV = 0.7 # je Sendung in Folge: Schwelle * diesen Faktor
LERN_SCHRITT_UPDATE = 1   # je eingespieltem Template-Update seit der letzten Sendung: Schwelle - so viele Tage
SCHWELLE_MIN = 2          # Arbeitstage, Untergrenze der gelernten Schwelle
SCHWELLE_MAX = 30         # Arbeitstage, Obergrenze der gelernten Schwelle
TEMPLATE_JSON_REL = ".claude/template.json"
CONFIG_REL = "AI-CONFIG.md"


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


def _feedback_modul(root: Path):
    """feedback.py per importlib - dort stehen Parser, Schalterlesen, der Zustand und der atomare
    Schreibzugriff auf template.json (_template_json_schreiben), den dieses Script fuer seinen eigenen
    Lern-Merker mitbenutzt statt einen zweiten Mechanismus zu bauen. Fehlt es (Projekt ohne Rueckmeldung),
    gibt es hier auch nichts zu tun."""
    import importlib.util
    pfad = root / ".claude" / "scripts" / "feedback.py"
    if not pfad.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_fb_check", pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - ein kaputtes feedback.py darf die Sitzung nicht aufhalten
        return None


def _arbeitstage_seit(root: Path, stempel: str) -> int:
    """Tage mit mindestens einem Commit seit `stempel` (JJJJ-MM-TT HH:MM). Ohne Stempel: seit jeher."""
    seit = (stempel or "")[:10]
    args = ["git", "-C", str(root), "log", "--format=%ad", "--date=short"]
    if seit:
        args.append(f"--since={seit}")
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return 0
    if res.returncode != 0:
        return 0
    return len(set(res.stdout.split()))


def _pausiert_bis(block: dict) -> str:
    """Gibt das Pausier-Datum zurueck, wenn 'erinnerung_pausiert_bis' (feedback-Block in template.json)
    gesetzt ist und noch in der Zukunft liegt - sonst leeren String. ISO-Datum (JJJJ-MM-TT) vergleicht sich
    als String korrekt gegen das heutige Datum."""
    bis = str(block.get("erinnerung_pausiert_bis") or "").strip()
    if not bis:
        return ""
    return bis if bis > time.strftime("%Y-%m-%d") else ""


def _updates_seit(tj: dict, zuletzt_gesendet: str) -> int:
    """Anzahl der Eintraege in .claude/template.json § "updates" (siehe update-template.py), deren Datum NACH
    der letzten Sendung liegt. Ohne bisherige Sendung zaehlen alle Updates."""
    seit = (zuletzt_gesendet or "")[:10]
    updates = tj.get("updates")
    if not isinstance(updates, list):
        return 0
    if not seit:
        return len(updates)
    return sum(1 for u in updates if isinstance(u, dict) and str(u.get("date") or "") > seit)


def _adaptive_schwelle(tj: dict, block: dict, zuletzt_gesendet: str):
    """Berechnet die dynamische Schwelle (Arbeitstage) fuer Takt "adaptiv" - siehe Kopfkommentar fuer die
    Herleitung. Gibt (schwelle: int, begruendung: str) zurueck; die Begruendung ist fuer --status gedacht,
    damit die Rechnung nachvollziehbar bleibt statt eine Blackbox zu sein."""
    ohne_reaktion = int(block.get("erinnerungen_ohne_reaktion") or 0)
    verschoben = int(block.get("verschiebungen") or 0)
    in_folge_gesendet = int(block.get("sendungen_in_folge") or 0)
    updates_seit = _updates_seit(tj, zuletzt_gesendet)

    schwelle = FAELLIG_TAGE * (LERN_FAKTOR_NEGATIV ** (ohne_reaktion + verschoben))
    schwelle = min(schwelle, float(SCHWELLE_MAX))
    schwelle = schwelle * (LERN_FAKTOR_POSITIV ** in_folge_gesendet)
    schwelle = max(schwelle, float(SCHWELLE_MIN))
    schwelle = schwelle - updates_seit * LERN_SCHRITT_UPDATE
    schwelle = max(schwelle, float(SCHWELLE_MIN))
    schwelle = min(max(round(schwelle), SCHWELLE_MIN), SCHWELLE_MAX)

    teile = [f"Basis {FAELLIG_TAGE}"]
    if ohne_reaktion:
        teile.append(f"{ohne_reaktion}x ignoriert")
    if verschoben:
        teile.append(f"{verschoben}x verschoben")
    if in_folge_gesendet:
        teile.append(f"{in_folge_gesendet}x in Folge gesendet")
    if updates_seit:
        teile.append(f"{updates_seit} Update{'e' if updates_seit != 1 else ''}")
    return schwelle, ", ".join(teile)


def _merker_fortschreiben(block: dict, arbeitstage: int, schwelle: int) -> bool:
    """NUR aufrufen, wenn diese Erinnerung tatsaechlich angezeigt wird (nicht bei --status - das bleibt rein
    lesend). Zaehlt "erinnerungen_ohne_reaktion" hoch, wenn schon FRUEHER (an einem anderen Kalendertag)
    erinnert wurde, ohne dass seither gesendet wurde - die allererste Erinnerung eines Zyklus zaehlt noch
    nicht als "ignoriert". Hoechstens ein Zaehlschritt je Kalendertag, damit mehrere Sitzungen am selben Tag
    den Zaehler nicht ueberproportional hochtreiben. Aendert `block` in place und gibt True zurueck, wenn
    etwas zu speichern ist."""
    if arbeitstage < schwelle:
        return False
    heute = time.strftime("%Y-%m-%d")
    letzte = block.get("letzte_erinnerung") or ""
    if letzte == heute:
        return False
    if letzte:
        block["erinnerungen_ohne_reaktion"] = int(block.get("erinnerungen_ohne_reaktion") or 0) + 1
        block["sendungen_in_folge"] = 0
    block["letzte_erinnerung"] = heute
    return True


def _faellig_takt(modus: str, takt: str, stunden: float, arbeitstage: int, schwelle, takt_stunden: dict) -> bool:
    """Faelligkeit nach Takt: "aus" und "manuell" (Feedback-Modus) erinnern nie. "adaptiv" vergleicht die
    Arbeitstage mit der gelernten `schwelle`; jeder andere Takt mit einem Abstand aus TAKT_STUNDEN
    (feedback.py) wird nach diesem Abstand faellig - Takt "manuell" hat dort keinen Abstand (None) und wird
    nie faellig. MINDESTABSTAND_H bleibt in jedem Fall die Untergrenze."""
    if modus in ("aus", "manuell"):
        return False
    if takt == "adaptiv":
        return arbeitstage >= schwelle and stunden >= MINDESTABSTAND_H
    abstand = takt_stunden.get(takt)
    if abstand is None:
        return False
    return stunden >= max(abstand, MINDESTABSTAND_H)


def main() -> int:
    root = _root()
    fb = _feedback_modul(root)
    if fb is None:
        return 0
    ist_status = "--status" in sys.argv[1:]
    try:
        tj = fb._template_json(root)
        if tj.get("is_template") is True:
            return 0
        modus = fb._modus(root)
        takt = fb._takt(root)
        block = fb._feedback_block(tj)
        zuletzt = block.get("zuletzt_gesendet") or ""
        wartend = len(fb._outbox(root))
        stunden = fb._tage_seit(zuletzt) * 24.0
        pausiert_bis = _pausiert_bis(block)
        if takt == "adaptiv":
            arbeitstage = _arbeitstage_seit(root, zuletzt)
            schwelle, begruendung = _adaptive_schwelle(tj, block, zuletzt)
        else:
            arbeitstage, schwelle, begruendung = 0, FAELLIG_TAGE, ""
    except Exception:  # noqa: BLE001 - siehe oben: nie die Sitzung aufhalten
        return 0

    faellig = not pausiert_bis and _faellig_takt(modus, takt, stunden, arbeitstage, schwelle, fb.TAKT_STUNDEN)

    # Den Lern-Merker nur beim ECHTEN Hook-Lauf fortschreiben, nicht bei --status: Status ist reine Anzeige
    # und darf die Rechnung, die er gerade zeigt, nicht selbst veraendern.
    if faellig and not ist_status and takt == "adaptiv":
        try:
            if _merker_fortschreiben(block, arbeitstage, schwelle):
                tj["feedback"] = block
                fb._template_json_schreiben(root, tj)
        except Exception:  # noqa: BLE001 - ein fehlgeschlagener Merker darf die Erinnerung nicht verhindern
            pass

    if ist_status:
        print(f"Feedback: {modus}, Takt: {takt}")
        print(f"Zuletzt gesendet: {zuletzt or 'nie'} ({stunden / 24:.1f} Tage her)")
        if takt == "adaptiv":
            print(f"Arbeitstage seitdem: {arbeitstage}")
            print(f"Schwelle: {schwelle} Arbeitstage ({begruendung})")
        if pausiert_bis:
            print(f"Pausiert bis: {pausiert_bis} (feedback.py --verschieben <Tage>)")
        print(f"Wartende Eintraege: {wartend}")
        print("Faellig: " + ("ja" if faellig else "nein"))
        return 0

    if faellig:
        was = f"{wartend} Eintrag/Eintraege warten" if wartend else "noch nichts gesammelt"
        grund = (f"{arbeitstage} Arbeitstage seit der letzten Sendung" if takt == "adaptiv"
                 else f"Takt '{takt}', {stunden / 24:.1f} Tage seit der letzten Sendung")
        if modus == "bestätigen":
            print(f"Rueckmeldung ans Template waere faellig ({grund}, {was}).")
            print("a) ansehen und senden: /act-feedback   b) verschieben (Tage) oder Takt aendern   "
                  "c) nicht mehr erinnern (Feedback auf manuell)")
        else:
            print(f"Rueckmeldung ans Template waere faellig ({grund}, {was}). "
                  f"Ansehen: /act-feedback - oder ein Satz genuegt: /act-feedback <Text>.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
