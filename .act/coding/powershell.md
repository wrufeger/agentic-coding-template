# Coding rules — PowerShell

summary: pinned PowerShell edition, encoding, strict mode and errors, native exit codes, script style, PSScriptAnalyzer and Pester

Rules for PowerShell scripts and modules. Group IDs (`CR-powershell-<name>`) are stable and never
reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in this
header.

## `CR-powershell-edition` — Pin the edition, keep encoding explicit

summary: Windows PowerShell 5.1 versus PowerShell 7, one target per script, explicit encoding, no Bash syntax

- Name the target in the project: Windows PowerShell 5.1 (`powershell.exe`) or PowerShell 7+ (`pwsh`).
  Check `$PSVersionTable.PSVersion` and the project files before applying anything below (`R-code-version`);
  declare it in the script with `#Requires -Version 5.1` or `#Requires -Version 7.0`.
- The two editions differ in defaults: 5.1 writes UTF-16 LE with `>`, `>>` and `Out-File`, and `Set-Content`
  uses the ANSI code page; 7 writes UTF-8 without BOM everywhere. Never rely on the default — pass
  `-Encoding utf8` (5.1 adds a BOM; `utf8NoBOM` exists only in 7) to every `Out-File`, `Set-Content`,
  `Add-Content` and `Export-Csv`, and keep an existing file's encoding (`R-code-encoding`).
- Do not mix in Bash syntax: no `&&`/`||` between commands (only PowerShell 7 has them), no `export VAR=...`
  (use `$env:VAR = ...`), no `rm -rf` (use `Remove-Item -Recurse` on a path you checked).
- Paths: build them with `Join-Path` and `$PSScriptRoot`, never by concatenating `\`; quote paths that may
  contain spaces; use `-LiteralPath` when a name may contain `[` or `]`.

## `CR-powershell-strictness` — Strict mode and errors that stop

summary: Set-StrictMode, ErrorActionPreference Stop, native exit codes, try/catch with the failing value

- Start a script with `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'`; a non-terminating
  error otherwise lets the script carry on with bad data.
- A native program (`git`, `docker`, `npm`) does not raise an error on failure, and `$ErrorActionPreference`
  does not catch it: check `$LASTEXITCODE` right after the call and `throw` or `exit` with a message
  naming the command and the code. PowerShell 7.4+ can do this with `$PSNativeCommandUseErrorActionPreference
  = $true`; 5.1 cannot.
- Catch specific failures in `try`/`catch`, and name what failed and with what value
  (`"Cannot read '$Path': $($_.Exception.Message)"`); never an empty `catch {}`. Use `-ErrorAction
  SilentlyContinue` only on a single call whose failure is expected and tested afterwards.
- Set exit codes deliberately (`exit 0`/`exit 1`) at the end of a script that CI or another program calls;
  write errors with `Write-Error` or `throw`, not `Write-Host`.

## `CR-powershell-style` — Names, parameters, no aliases

summary: approved verbs, advanced functions, param blocks with types, full cmdlet names, output as objects

- Name functions `Verb-Noun` with an approved verb (`Get-Verb` lists them: `Get-`, `Set-`, `New-`,
  `Remove-`, `Test-`, `Invoke-` …); a singular noun, no `Do-`, `Run-` or `Check-`.
- Write a function as an advanced function: `[CmdletBinding()]`, a `param()` block with a type on every
  parameter, `[Parameter(Mandatory)]` and `[ValidateSet()]`/`[ValidateNotNullOrEmpty()]` where they fit.
  Mark functions that change state with `SupportsShouldProcess` and honour `-WhatIf`.
- No aliases in a script (`ls`, `gci`, `%`, `?`, `foreach` for `ForEach-Object`, `curl`, `wget`) and no
  positional parameters for anything beyond the first; write the full cmdlet and parameter name. `curl` and
  `wget` are aliases of `Invoke-WebRequest` in 5.1, not the programs.
- Return objects, not formatted text: no `Format-Table` or `Write-Host` in a function whose output is used
  further; use `Write-Verbose` for progress and `Write-Output` or an implicit return for the result.

## `CR-powershell-toolchain` — Lint and tests

summary: PSScriptAnalyzer for lint, Pester 5 for tests, or what the project has set up

- `PSScriptAnalyzer` (`Invoke-ScriptAnalyzer -Path . -Recurse`) is the template's usual linter; keep its
  settings in a `PSScriptAnalyzerSettings.psd1` in the project and do not exclude rules wholesale.
- `Pester` is the usual test runner; check the installed major version first (`Get-Module Pester
  -ListAvailable`) — Pester 5 needs `BeforeAll` for setup and discovery-time code differs from run-time code,
  so Pester 3/4 tests do not run unchanged. Run it with `Invoke-Pester -CI`.
- Either way, run what the project has configured and install nothing unasked (`R-code-tools`).
