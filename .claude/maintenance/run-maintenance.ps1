# Zweck: Headless-Wartungslauf ueber den Skill /maintenance (.claude/skills/maintenance/SKILL.md) anstossen,
#        fuer einen Aufruf aus dem Windows Task Scheduler heraus (siehe .claude/maintenance/README.md).
# Aufruf: pwsh -File .claude/maintenance/run-maintenance.ps1 [-Modus kurz|docs|deps|alle]
# Ausgabeformat: Log-Datei .claude/maintenance/run-YYYY-MM-DD-HHmmss.log (gitignored), Exit-Code 0 = ok.

param(
    [ValidateSet("kurz", "docs", "deps", "alle")]
    [string]$Modus = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot | Split-Path -Parent
$logDir = Join-Path $PSScriptRoot "."
$timestamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$logFile = Join-Path $logDir "run-$timestamp.log"

$prompt = if ($Modus) { "/maintenance $Modus" } else { "/maintenance" }

Push-Location $root
try {
    # "claude" ist die Claude-Code-CLI; -p fuehrt einen einzelnen Prompt headless (non-interaktiv) aus.
    & claude -p $prompt *> $logFile
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Error "Wartungslauf fehlgeschlagen (Exit-Code $exitCode), siehe $logFile"
}
exit $exitCode
