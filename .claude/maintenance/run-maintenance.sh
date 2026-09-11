#!/usr/bin/env bash
# Zweck: Headless-Wartungslauf ueber den Skill /maintenance (.claude/skills/maintenance/SKILL.md) anstossen,
#        fuer einen Aufruf aus cron/systemd-timer heraus (siehe .claude/maintenance/README.md).
# Aufruf: ./.claude/maintenance/run-maintenance.sh [kurz|docs|deps|alle]
# Ausgabeformat: Log-Datei .claude/maintenance/run-YYYY-MM-DD-HHMMSS.log (gitignored), Exit-Code 0 = ok.

set -euo pipefail

modus="${1:-}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/../.." && pwd)"
timestamp="$(date +%Y-%m-%d-%H%M%S)"
log_file="$script_dir/run-$timestamp.log"

if [ -n "$modus" ]; then
    prompt="/maintenance $modus"
else
    prompt="/maintenance"
fi

cd "$root"
# "claude" ist die Claude-Code-CLI; -p fuehrt einen einzelnen Prompt headless (non-interaktiv) aus.
if claude -p "$prompt" > "$log_file" 2>&1; then
    exit 0
else
    code=$?
    echo "Wartungslauf fehlgeschlagen (Exit-Code $code), siehe $log_file" >&2
    exit "$code"
fi
