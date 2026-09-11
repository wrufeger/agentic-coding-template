#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Agenten-Protokoll `ai.log` im Projekt-Root schreiben und mitlesen (siehe AGENTS.md § "Logging
#        (optional)" und CLAUDE.md § 7 "Nummerierung"). Zwei Einsatzwege: CLI-Modus fuer jeden Assistenten
#        mit Shell-Zugriff, Hook-Modus fuer Claude-Code-Hooks (liest die Hook-Payload als JSON von stdin).
#        Reine Python-Stdlib, kein Paket noetig. Der Schalter `AI_LOG`/`AI_LOG_LEVEL` steht in AGENTS.md und
#        kann per gleichnamiger Umgebungsvariable je Lauf uebersteuert werden. Bei `AI_LOG=aus` ist jeder
#        Aufruf ein No-op (auch die Zustands-/Rohdateien unten entstehen dann nicht).
#
# Aufruf:
#   python .claude/scripts/ai-log.py LEVEL agent topic Text...      # eine Zeile schreiben (CLI-Modus)
#   python .claude/scripts/ai-log.py --hook [EVENT]                 # Hook-Payload von stdin lesen
#   python .claude/scripts/ai-log.py --tail [--grep MUSTER] [--lines N] [--no-color]
#   python .claude/scripts/ai-log.py --reset                        # ai.log -> ai.log.<zeitstempel>.bak
#   python .claude/scripts/ai-log.py --status                       # effektive Konfiguration + Zaehlerstand
#   python .claude/scripts/ai-log.py --help
#
# Env AI_LOG_RAW=1 (Diagnose-Schalter, nur bei eingeschaltetem Logging wirksam): schreibt im Hook-Modus
#   zusaetzlich JEDE vollstaendige Hook-Payload als eine JSON-Zeile nach `ai.log.raw.jsonl` — UNMASKIERT,
#   also mit echten Secrets/Tokens falls in der Payload enthalten. Nur fuer die kurze Fehlersuche an den
#   echten Hook-Feldern nutzen, danach Datei loeschen; sie ist gitignored, aber nicht sicher genug fuer den
#   Dauerbetrieb.
#
# Ausgabeformat einer Log-Zeile:
#   [YYYY-MM-DD HH:MM:SS] [LEVEL] [agent] [topic] Text
#   `agent` ist bei Sub-Agenten durchnummeriert (`builder#1`, `builder#2`, ...) — Zaehler und die Zuordnung
#   `agent_id -> Label` je Sitzung liegen in `ai.log.state.json` (gitignored, wird bei fehlendem/kaputtem
#   Inhalt still neu angelegt), Schreibzugriffe bestenmoeglich per Lock-Datei `ai.log.state.lock` seriali-
#   siert (Spin <= 1s, verwaiste Locks > 5s werden uebernommen; schlaegt das Sperren fehl, wird ohne Lock
#   weitergearbeitet — ein Hook darf dadurch nie blockieren).
#
# Exit-Codes: 0 = ok (auch bei "aus" oder Laufzeitfehlern im Hook-/CLI-Betrieb, siehe unten),
#             2 = Usage-Fehler (falsche Argumentzahl im CLI-Modus).
# Ein Fehler dieses Scripts darf nie einen Hook oder den Aufrufer stoeren: main() laeuft komplett in
# try/except, im Hook-Modus wird NIE etwas auf stdout ausgegeben (Claude Code fuegt stdout von
# UserPromptSubmit-Hooks als Kontext ein).

import json
import os
import re
import sys

# Konsolenausgabe (--tail/--status/--reset) immer UTF-8, unabhaengig von der Windows-Codepage.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
import time
from pathlib import Path

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
EIN_WERTE = {"ein", "an", "on", "1", "true", "yes", "ja"}

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _parse_agents_md(root: Path):
    """Liest AI_LOG/AI_LOG_LEVEL aus dem Schalter-Block in AGENTS.md.

    Gibt (ai_log_wert_oder_None, ai_log_level_wert_oder_None) zurueck.
    """
    agents_md = root / "AGENTS.md"
    if not agents_md.exists():
        return None, None
    try:
        text = agents_md.read_text(encoding="utf-8")
    except OSError:
        return None, None

    ai_log = None
    ai_log_level = None

    # Dokumentiert ist `AI_LOG=ein` ohne Leerzeichen; `AI_LOG = ein` wird trotzdem akzeptiert,
    # sonst haelt {{AUFTRAGGEBER}} das Log fuer eingeschaltet, waehrend still nichts geschrieben wird.
    m = re.search(r"^[ \t]*AI_LOG[ \t]*=[ \t]*([^\s#]+)", text, re.MULTILINE)
    if m:
        ai_log = m.group(1).strip()
    m = re.search(r"^[ \t]*AI_LOG_LEVEL[ \t]*=[ \t]*([^\s#]+)", text, re.MULTILINE)
    if m:
        ai_log_level = m.group(1).strip()

    return ai_log, ai_log_level


def load_config():
    """Ermittelt die effektive Konfiguration.

    Rueckgabe: dict mit root, log_file, enabled (bool), level (str),
    source_enabled / source_level ("AGENTS.md" | "env" | "default").
    """
    root = _find_root()
    log_file = root / "ai.log"

    agents_enabled, agents_level = _parse_agents_md(root)

    env_enabled = os.environ.get("AI_LOG")
    env_level = os.environ.get("AI_LOG_LEVEL")

    if env_enabled:
        enabled_raw = env_enabled
        source_enabled = "env"
    elif agents_enabled is not None:
        enabled_raw = agents_enabled
        source_enabled = "AGENTS.md"
    else:
        enabled_raw = "aus"
        source_enabled = "default"

    enabled = enabled_raw.strip().lower() in EIN_WERTE

    if env_level:
        level_raw = env_level
        source_level = "env"
    elif agents_level is not None:
        level_raw = agents_level
        source_level = "AGENTS.md"
    else:
        level_raw = "INFO"
        source_level = "default"

    level = level_raw.strip().upper()
    if level not in LEVELS:
        level = "INFO"

    return {
        "root": root,
        "log_file": log_file,
        "enabled": enabled,
        "level": level,
        "source_enabled": source_enabled,
        "source_level": source_level,
    }


# ---------------------------------------------------------------------------
# Text-Sanitizing
# ---------------------------------------------------------------------------

# Schluessel=Wert / Schluessel: Wert. Ein vorangestelltes Schema (Bearer/Basic/...) gehoert mit in den
# maskierten Teil, sonst bliebe bei "Authorization: Bearer xyz" genau das Token xyz stehen.
_SECRET_KV_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|authorization|bearer)\s*[=:]\s*"
    r"((?:(?:bearer|basic|token|jwt)\s+)?[^\s\"']+)"
)
# Leerzeichen-getrennte Kommandozeilen-Schalter: --password x, --secret-access-key x, -token x.
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--?[a-z0-9-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential)"
    r"[a-z0-9-]*)[ \t]+([^\s\"']+)"
)
# Zugangsdaten in URLs: postgres://user:pass@host, https://user:token@github.com/...
_SECRET_URL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s/:@]+):([^\s/@]+)@")
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abp]-[A-Za-z0-9-]{8,}"),
]


def _kv_replace(m: "re.Match") -> str:
    # m.group(0) ist z.B. "token=abc123", group(1) der Schluesselname, group(2) der Wert.
    prefix = m.group(0)[: len(m.group(0)) - len(m.group(2))]
    return prefix + "***"


def mask_secrets(text: str) -> str:
    """Ersetzt erkennbare Secrets im Text durch ***."""
    if not text:
        return text
    text = _SECRET_URL_RE.sub(r"\1:***@", text)
    text = _SECRET_KV_RE.sub(_kv_replace, text)
    text = _SECRET_FLAG_RE.sub(r"\1 ***", text)
    for pat in _SECRET_PATTERNS:
        text = pat.sub("***", text)
    return text


def clean_text(text: str) -> str:
    """Whitespace normalisieren, kuerzen, Secrets maskieren."""
    if text is None:
        text = ""
    text = str(text)
    # Riesige Eingaben (eingefuegte Dateien, MCP-Rohdaten) vorab kappen: es bleiben ohnehin nur
    # 200 Zeichen uebrig, und die Regexe sollen nicht ueber Megabytes laufen.
    if len(text) > 8000:
        text = text[:8000]
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = mask_secrets(text)
    if len(text) > 200:
        text = text[:199] + "…"
    return text


def _short(text, limit: int) -> str:
    """Wie clean_text, aber mit frei waehlbarer Kuerzungslaenge (fuer Hook-Kurzargumente)."""
    if text is None:
        text = ""
    text = str(text)
    if len(text) > 8000:
        text = text[:8000]
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = mask_secrets(text)
    if len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text


def _strip_prefix(name) -> str:
    """Schneidet ein Plugin-Praefix ("xyz:builder" -> "builder") ab."""
    name = str(name or "")
    if ":" in name:
        name = name.split(":", 1)[1]
    return name


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

_LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}


def _level_ok(line_level: str, configured_level: str) -> bool:
    return _LEVEL_RANK.get(line_level, 1) >= _LEVEL_RANK.get(configured_level, 1)


def write_line(cfg, level: str, agent: str, topic: str, text: str) -> None:
    """Schreibt eine Zeile, sofern eingeschaltet und Level ausreicht. Sonst No-op."""
    level = level.upper()
    if level not in LEVELS:
        level = "INFO"
    if not cfg["enabled"]:
        return
    if not _level_ok(level, cfg["level"]):
        return

    # Eckige Klammern muessen raus, sonst zerlegt --tail die Zeile falsch (Format [ts] [level] [agent] ...).
    agent = re.sub(r"[\s()\[\]]+", "", str(agent).lower()) or "system"
    topic = re.sub(r"[\s()\[\]]+", "", str(topic).lower()) or "session"
    text = clean_text(text)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] [{agent}] [{topic}] {text}\n"

    log_file = cfg["log_file"]
    with open(log_file, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Nummerierung: Zustandsdatei `ai.log.state.json` + Lock `ai.log.state.lock`
# ---------------------------------------------------------------------------

SESSION_MAX_AGE = 24 * 3600  # Sitzungen aelter als 24h werden beim Schreiben entfernt.
PENDING_MAX_AGE = 10 * 60  # pending-Eintraege aelter als 10 min gelten als verwaist.
LOCK_TIMEOUT = 1.0  # max. Wartezeit auf das Lock (Sekunden).
LOCK_STALE_AFTER = 5.0  # Lock aelter als das gilt als verwaist und wird uebernommen.
LOCK_SPIN_SLEEP = 0.02


def _state_paths(root: Path):
    return root / "ai.log.state.json", root / "ai.log.state.lock"


class _StateLock:
    """Bestmoegliches Datei-Lock ueber os.open(O_CREAT|O_EXCL). Blockiert nie dauerhaft: nach
    LOCK_TIMEOUT wird ohne Lock weitergearbeitet, ein verwaistes Lock (> LOCK_STALE_AFTER) wird
    uebernommen. `held` sagt, ob das Lock tatsaechlich gehalten wird (nur informativ)."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.held = False

    def __enter__(self):
        deadline = time.time() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_AFTER:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    self.held = False
                    return self
                time.sleep(LOCK_SPIN_SLEEP)
            except OSError:
                self.held = False
                return self

    def __exit__(self, *exc_info):
        if self.held:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        return False


def _load_state(state_path: Path) -> dict:
    """Liest die Zustandsdatei; fehlt sie oder ist sie kaputt, wird still neu begonnen."""
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {"sessions": {}}


def _save_state(state_path: Path, state: dict, now: float) -> None:
    """Schreibt die Zustandsdatei, Sitzungen aelter als SESSION_MAX_AGE fallen dabei weg."""
    cutoff = now - SESSION_MAX_AGE
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    cleaned = {}
    for sid, sess in sessions.items():
        if isinstance(sess, dict) and isinstance(sess.get("last"), (int, float)) and sess["last"] >= cutoff:
            cleaned[sid] = sess
    state["sessions"] = cleaned
    try:
        with open(state_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError:
        pass


def _ensure_session(state: dict, session_id) -> dict:
    key = session_id if session_id else "-"
    sessions = state.setdefault("sessions", {})
    sess = sessions.get(key)
    if not isinstance(sess, dict):
        sess = {}
        sessions[key] = sess
    if not isinstance(sess.get("counters"), dict):
        sess["counters"] = {}
    if not isinstance(sess.get("ids"), dict):
        sess["ids"] = {}
    if not isinstance(sess.get("pending"), dict):
        sess["pending"] = {}
    return sess


def _add_pending(root: Path, session_id, agent_type: str, auftrag: str, name=None, model=None, now=None) -> None:
    """Merkt einen Delegationsauftrag vor, bis der passende SubagentStart-Hook eintrifft."""
    now = now if now is not None else time.time()
    state_path, lock_path = _state_paths(root)
    with _StateLock(lock_path):
        state = _load_state(state_path)
        sess = _ensure_session(state, session_id)
        entry = {"ts": now, "auftrag": auftrag or ""}
        if name:
            entry["name"] = name
        if model:
            entry["model"] = model
        sess["pending"].setdefault(agent_type, []).append(entry)
        sess["last"] = now
        _save_state(state_path, state, now)


def _start_subagent(root: Path, session_id, agent_type: str, agent_id, now=None):
    """Vergibt die naechste Nummer fuer `agent_type` in dieser Sitzung, ordnet `agent_id` das Label
    zu und entnimmt den aeltesten passenden pending-Eintrag (verwirft dabei zu alte).

    Rueckgabe: (label, pending_entry_oder_None).
    """
    now = now if now is not None else time.time()
    state_path, lock_path = _state_paths(root)
    with _StateLock(lock_path):
        state = _load_state(state_path)
        sess = _ensure_session(state, session_id)
        n = int(sess["counters"].get(agent_type, 0)) + 1
        sess["counters"][agent_type] = n
        label = f"{agent_type}#{n}"
        if agent_id:
            sess["ids"][str(agent_id)] = label

        pending_list = sess["pending"].get(agent_type, [])
        entry = None
        while pending_list:
            candidate = pending_list.pop(0)
            ts = candidate.get("ts", 0) if isinstance(candidate, dict) else 0
            if isinstance(ts, (int, float)) and (now - ts) <= PENDING_MAX_AGE:
                entry = candidate
                break
            # sonst: verwaister/zu alter Eintrag, verwerfen und naechsten pruefen.
        sess["pending"][agent_type] = pending_list

        sess["last"] = now
        _save_state(state_path, state, now)
    return label, entry


def _resolve_label(root: Path, session_id, agent_type: str, agent_id: str, now=None) -> str:
    """Label fuer eine Hook-Zeile mit `agent_id`. Bekannt -> aus `ids`. Unbekannt -> Nummer lazy
    vergeben (wie beim Start, aber ohne pending-Zuordnung)."""
    now = now if now is not None else time.time()
    state_path, lock_path = _state_paths(root)
    with _StateLock(lock_path):
        state = _load_state(state_path)
        sess = _ensure_session(state, session_id)
        label = sess["ids"].get(agent_id)
        if label:
            return label
        n = int(sess["counters"].get(agent_type, 0)) + 1
        sess["counters"][agent_type] = n
        label = f"{agent_type}#{n}"
        sess["ids"][agent_id] = label
        sess["last"] = now
        _save_state(state_path, state, now)
        return label


def _status_session_lines(root: Path):
    """Fuer --status: je Sitzung (neueste zuerst, max. 3) Zaehler je Typ + naechste freie Nummer."""
    state_path, _lock_path = _state_paths(root)
    state = _load_state(state_path)
    sessions = state.get("sessions", {})
    if not isinstance(sessions, dict):
        return []
    items = sorted(
        sessions.items(),
        key=lambda kv: kv[1].get("last", 0) if isinstance(kv[1], dict) else 0,
        reverse=True,
    )
    lines = []
    for sid, sess in items[:3]:
        if not isinstance(sess, dict):
            continue
        counters = sess.get("counters")
        if not isinstance(counters, dict) or not counters:
            continue
        parts = [f"{typ}: {n} gestartet, nächste #{int(n) + 1}" for typ, n in counters.items()]
        lines.append(f"  session {sid}: " + "; ".join(parts))
    return lines


# ---------------------------------------------------------------------------
# Hook-Modus
# ---------------------------------------------------------------------------


def _agent_name(payload: dict) -> str:
    """Fallback-Name ohne Nummerierung: `agent_type` (Praefix abgeschnitten) oder "orchestrator"."""
    agent = payload.get("agent_type")
    if not agent:
        return "orchestrator"
    return _strip_prefix(agent) or "orchestrator"


def _agent_type_raw(payload: dict):
    t = payload.get("agent_type")
    if not t:
        return None
    return _strip_prefix(t) or None


def _resolve_hook_agent(cfg, payload: dict, session_id, agent_id, now: float) -> str:
    """Label fuer eine beliebige Hook-Zeile: mit `agent_id` -> nummeriertes Label (bekannt oder lazy
    vergeben); ohne `agent_id` -> unveraendert `orchestrator` bzw. `agent_type`, wie bisher."""
    top_level = _agent_name(payload)
    if not agent_id or not cfg["enabled"]:
        return top_level
    agent_type = _agent_type_raw(payload) or "subagent"
    return _resolve_label(cfg["root"], session_id, agent_type, str(agent_id), now)


def _first_str_field(d: dict, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _tool_response_to_text(resp) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in ("content", "text", "result"):
            v = resp.get(key)
            if isinstance(v, str) and v:
                return v
        try:
            return json.dumps(resp, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(resp)
    if isinstance(resp, list):
        try:
            return json.dumps(resp, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(resp)
    return str(resp)


def _short_arg_for_tool(tool_name: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool_name == "Bash":
        val = tool_input.get("command", "")
    elif tool_name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        val = tool_input.get("file_path", "")
    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path")
        val = f"{pattern} path={path}" if path else pattern
    elif tool_name == "Skill":
        val = tool_input.get("skill", "")
    elif tool_name == "WebFetch":
        val = tool_input.get("url", "")
    else:
        val = ""
        for v in tool_input.values():
            if isinstance(v, str) and v:
                val = v
                break
    return _short(val, 120)


def _append_raw(root: Path, payload: dict) -> None:
    """Diagnose-Schalter AI_LOG_RAW=1: volle, UNMASKIERTE Payload als JSON-Zeile anhaengen."""
    path = root / "ai.log.raw.jsonl"
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handle_hook(cfg, event_arg: str) -> None:
    """Liest die Hook-Payload von stdin (JSON) und schreibt ggf. eine Zeile.

    Gibt NIE etwas auf stdout aus. Ein unlesbares Payload wird bei eingeschaltetem Log immer als
    ERROR vermerkt (unabhaengig vom konfigurierten Level).
    """
    # Hook-Payloads kommen als UTF-8; nicht die Konsolen-Codepage (Windows: cp1252) verwenden.
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, ValueError):
        write_line(cfg, "ERROR", "system", "error", "hook-payload unlesbar")
        return

    if cfg["enabled"] and os.environ.get("AI_LOG_RAW", "").strip() == "1":
        _append_raw(cfg["root"], payload)

    event = payload.get("hook_event_name") or event_arg or ""
    session_id = payload.get("session_id")
    agent_id = payload.get("agent_id")
    now = time.time()

    if event == "SessionStart":
        source = payload.get("source")
        text = "start" + (f" · source={source}" if source else "")
        write_line(cfg, "INFO", "orchestrator", "session", text)

    elif event == "SessionEnd":
        reason = payload.get("reason")
        text = "ende" + (f" · reason={reason}" if reason else "")
        write_line(cfg, "INFO", "orchestrator", "session", text)

    elif event == "UserPromptSubmit":
        write_line(cfg, "INFO", "user", "prompt", payload.get("prompt", ""))

    elif event == "PreToolUse":
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        label = _resolve_hook_agent(cfg, payload, session_id, agent_id, now)
        if tool_name == "Agent":
            subagent_type = _strip_prefix(tool_input.get("subagent_type") or "") or "general-purpose"
            auftrag = _first_str_field(tool_input, ("description", "prompt", "name")) or ""
            text = f"{subagent_type} ← {auftrag}"
            model = tool_input.get("model")
            if model:
                text += f" · model={model}"
            write_line(cfg, "INFO", label, "delegate", text)

            if cfg["enabled"]:
                pend_auftrag = tool_input.get("description")
                if not isinstance(pend_auftrag, str) or not pend_auftrag:
                    prompt = tool_input.get("prompt")
                    pend_auftrag = _short(prompt, 150) if isinstance(prompt, str) and prompt else None
                if not pend_auftrag:
                    name_field = tool_input.get("name")
                    pend_auftrag = name_field if isinstance(name_field, str) else ""
                pend_name = tool_input.get("name")
                pend_model = tool_input.get("model")
                _add_pending(
                    cfg["root"],
                    session_id,
                    subagent_type,
                    _short(pend_auftrag, 150),
                    name=pend_name if isinstance(pend_name, str) and pend_name else None,
                    model=pend_model if isinstance(pend_model, str) and pend_model else None,
                    now=now,
                )
        else:
            arg = _short_arg_for_tool(tool_name, tool_input)
            write_line(cfg, "DEBUG", label, "tool", f"{tool_name} {arg}")

    elif event == "PostToolUse":
        tool_name = payload.get("tool_name", "")
        if tool_name == "Agent":
            tool_input = payload.get("tool_input")
            if not isinstance(tool_input, dict):
                tool_input = {}
            label = _resolve_hook_agent(cfg, payload, session_id, agent_id, now)
            subagent_type = _strip_prefix(tool_input.get("subagent_type") or "") or "general-purpose"
            resp_text = _tool_response_to_text(payload.get("tool_response"))
            text = f"{subagent_type} → {_short(resp_text, 150)}"
            write_line(cfg, "DEBUG", label, "result", text)
        # andere Tools: bewusst nichts schreiben (zu laut).

    elif event == "PostToolUseFailure":
        tool_name = payload.get("tool_name", "")
        label = _resolve_hook_agent(cfg, payload, session_id, agent_id, now)
        fehler = _first_str_field(payload, ("error",))
        if fehler is None:
            resp = payload.get("tool_response")
            if isinstance(resp, str) and resp:
                fehler = resp
        if fehler is None:
            fehler = payload.get("message", "")
        text = f"{tool_name} fehlgeschlagen · {_short(fehler, 150)}"
        write_line(cfg, "ERROR", label, "error", text)

    elif event == "SubagentStart":
        agent_type = _agent_type_raw(payload) or "subagent"
        if cfg["enabled"]:
            label, pending_entry = _start_subagent(cfg["root"], session_id, agent_type, agent_id, now)
        else:
            label, pending_entry = f"{agent_type}#?", None

        # Undokumentierte, defensive Felder direkt auf der SubagentStart-Payload haben Vorrang vor pending.
        auftrag_override = _first_str_field(payload, ("description", "prompt", "name", "agent_name"))
        if auftrag_override:
            text = _short(auftrag_override, 150)
        elif pending_entry and pending_entry.get("auftrag"):
            text = pending_entry["auftrag"]
        else:
            text = "gestartet"
        if pending_entry and pending_entry.get("name"):
            text += f" · name={pending_entry['name']}"
        if pending_entry and pending_entry.get("model"):
            text += f" · model={pending_entry['model']}"
        write_line(cfg, "INFO", label, "start", text)

    elif event == "SubagentStop":
        label = _resolve_hook_agent(cfg, payload, session_id, agent_id, now)
        last_msg = payload.get("last_assistant_message")
        text = _short(last_msg, 150) if last_msg else "beendet"
        write_line(cfg, "INFO", label, "end", text)

    elif event == "Stop":
        reason = payload.get("stop_reason")
        text = "turn ende" + (f" · reason={reason}" if reason else "")
        write_line(cfg, "DEBUG", "orchestrator", "session", text)

    elif event == "Notification":
        typ = _first_str_field(payload, ("notification_type", "type", "matcher")) or ""
        message = payload.get("message", "")
        if typ == "permission_prompt":
            write_line(cfg, "INFO", "system", "session", f"wartet auf Freigabe · {message}")
        else:
            write_line(cfg, "DEBUG", "system", "session", f"{typ} · {message}")

    else:
        write_line(cfg, "DEBUG", "system", "session", f"hook {event}")


# ---------------------------------------------------------------------------
# --tail
# ---------------------------------------------------------------------------

_LEVEL_COLOR = {
    "DEBUG": "\x1b[90m",
    "WARN": "\x1b[33m",
    "ERROR": "\x1b[1;31m",
}
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_RESET = "\x1b[0m"

_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[(?P<level>[^\]]+)\] \[(?P<agent>[^\]]+)\] \[(?P<topic>[^\]]+)\] (?P<text>.*)$"
)


def _colorize(line: str) -> str:
    m = _LINE_RE.match(line.rstrip("\n"))
    if not m:
        return line.rstrip("\n")
    ts, level, agent, topic, text = (
        m.group("ts"),
        m.group("level"),
        m.group("agent"),
        m.group("topic"),
        m.group("text"),
    )
    if level == "INFO":
        agent_part = f"{_CYAN}[{agent}]{_RESET}"
        return f"{_DIM}[{ts}]{_RESET} [{level}] {agent_part} [{topic}] {text}"
    color = _LEVEL_COLOR.get(level, "")
    if color:
        return f"{_DIM}[{ts}]{_RESET} {color}[{level}] [{agent}] [{topic}] {text}{_RESET}"
    return f"{_DIM}[{ts}]{_RESET} [{level}] [{agent}] [{topic}] {text}"


def cmd_tail(cfg, grep: str, lines: int, no_color: bool) -> int:
    """Gibt die letzten `lines` Zeilen aus und folgt der Datei danach (Polling alle 0,3s).

    Liest im Binaermodus und dekodiert selbst als UTF-8, damit die Byte-Position (fuer seek/tell)
    unabhaengig von Text-Modus-Eigenheiten sauber bleibt.
    """
    log_file = cfg["log_file"]
    use_color = (not no_color) and sys.stdout.isatty()
    if os.name == "nt":
        os.system("")

    pattern = None
    if grep:
        try:
            pattern = re.compile(grep, re.IGNORECASE)
        except re.error as e:
            print(f"ai-log: ungueltiges --grep-Muster: {e}", file=sys.stderr)
            return 1

    def emit(line: str) -> None:
        if pattern and not pattern.search(line):
            return
        out = _colorize(line) if use_color else line.rstrip("\n")
        print(out, flush=True)

    while not log_file.exists():
        print(f"ai-log: warte auf {log_file} ...", file=sys.stderr)
        try:
            time.sleep(1.0)
        except KeyboardInterrupt:
            return 0

    try:
        with open(log_file, "rb") as f:
            data = f.read()
        pos = len(data)
        text = data.decode("utf-8", errors="replace")
        all_lines = text.splitlines(True)
        if all_lines and not all_lines[-1].endswith("\n"):
            # Schreiber war beim Lesen noch nicht fertig: unvollstaendige Zeile zurueckstellen.
            rest = all_lines.pop()
            pos -= len(rest.encode("utf-8", errors="replace"))
        tail_lines = all_lines[-lines:] if lines > 0 else []
        for line in tail_lines:
            emit(line)

        while True:
            try:
                size = log_file.stat().st_size
            except OSError:
                size = 0
            if size < pos:
                # Datei wurde geleert/rotiert -> neu von vorn.
                pos = 0
            try:
                with open(log_file, "rb") as f:
                    f.seek(pos)
                    new_bytes = f.read()
                new_pos = pos + len(new_bytes)
                new_text = new_bytes.decode("utf-8", errors="replace")
                if new_text:
                    for line in new_text.splitlines(True):
                        if line.endswith("\n"):
                            emit(line)
                        else:
                            # unvollstaendige letzte Zeile -> Position zurueckdrehen, spaeter erneut lesen.
                            new_pos -= len(line.encode("utf-8", errors="replace"))
                pos = new_pos
            except OSError:
                pass
            time.sleep(0.3)
    except KeyboardInterrupt:
        return 0
    return 0


# ---------------------------------------------------------------------------
# --reset / --status
# ---------------------------------------------------------------------------


def cmd_reset(cfg) -> int:
    log_file = cfg["log_file"]
    if not log_file.exists():
        print("ai-log: nichts zu tun (ai.log existiert nicht).")
        return 0
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = log_file.with_name(f"ai.log.{ts}.bak")
    try:
        log_file.rename(backup)
    except OSError as e:
        # Windows sperrt eine geoeffnete Datei: ein Editor oder ein Werkzeug haelt ai.log offen
        # (`--tail` selbst haelt sie nur kurz, kollidiert aber im Einzelfall).
        print(
            f"ai-log: {log_file} laesst sich nicht umbenennen ({e.strerror or e}).\n"
            f"ai-log: Datei ist vermutlich von einem anderen Programm geoeffnet "
            f"(Editor, tail -f, Viewer) - schliessen und erneut versuchen.",
            file=sys.stderr,
        )
        return 1
    print(f"ai-log: {log_file.name} -> {backup.name}")
    return 0


def cmd_status(cfg) -> int:
    print(f"root:            {cfg['root']}")
    print(f"logdatei:        {cfg['log_file']}")
    print(f"eingeschaltet:   {'ja' if cfg['enabled'] else 'nein'} (Quelle: {cfg['source_enabled']})")
    print(f"level:           {cfg['level']} (Quelle: {cfg['source_level']})")
    session_lines = _status_session_lines(cfg["root"])
    if session_lines:
        print("sitzungen (neueste zuerst, max. 3):")
        for line in session_lines:
            print(line)
    else:
        print("sitzungen:       keine (noch kein Sub-Agent ueber Hooks gestartet)")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------

USAGE = """\
Verwendung:
  ai-log.py LEVEL agent topic Text...       Zeile schreiben (LEVEL: DEBUG|INFO|WARN|ERROR)
  ai-log.py --hook [EVENT]                  Hook-Payload (JSON) von stdin lesen
  ai-log.py --tail [--grep MUSTER] [--lines N] [--no-color]
  ai-log.py --reset                         ai.log -> ai.log.<zeitstempel>.bak
  ai-log.py --status                        effektive Konfiguration + Zaehlerstand anzeigen
  ai-log.py --help

Env AI_LOG_RAW=1: schreibt im Hook-Modus jede volle (unmaskierte!) Payload nach ai.log.raw.jsonl.
"""


def _run(argv) -> int:
    if argv and argv[0] in ("--help", "-h"):
        sys.stdout.write(USAGE)
        return 0
    if not argv:
        sys.stderr.write(USAGE)
        return 2

    cfg = load_config()

    if argv[0] == "--hook":
        event_arg = argv[1] if len(argv) > 1 else ""
        handle_hook(cfg, event_arg)
        return 0

    if argv[0] == "--reset":
        return cmd_reset(cfg)

    if argv[0] == "--status":
        return cmd_status(cfg)

    if argv[0] == "--tail":
        rest = argv[1:]
        grep = ""
        lines = 20
        no_color = False
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--grep" and i + 1 < len(rest):
                grep = rest[i + 1]
                i += 2
            elif a == "--lines" and i + 1 < len(rest):
                try:
                    lines = int(rest[i + 1])
                except ValueError:
                    lines = 20
                i += 2
            elif a == "--no-color":
                no_color = True
                i += 1
            else:
                i += 1
        return cmd_tail(cfg, grep, lines, no_color)

    # CLI-Modus: LEVEL agent topic Text...
    if len(argv) < 4:
        sys.stderr.write(USAGE)
        return 2

    level, agent, topic = argv[0], argv[1], argv[2]
    if level.upper() not in LEVELS:
        sys.stderr.write(USAGE)
        return 2
    text = " ".join(argv[3:])
    write_line(cfg, level.upper(), agent, topic, text)
    return 0


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - bewusst breit, darf nie einen Hook stoeren
        is_hook = "--hook" in sys.argv[1:]
        if not is_hook:
            try:
                print(f"ai-log: Fehler: {e}", file=sys.stderr)
            except Exception:
                pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
