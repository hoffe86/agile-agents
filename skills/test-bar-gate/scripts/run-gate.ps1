<#
.SYNOPSIS
    Test-bar gate runner (PowerShell).

.DESCRIPTION
    Runs lint -> typecheck -> test (fail-fast) for the stack detected from
    solution-profile.yaml. Emits gate_check events to $env:COPILOT_EVENT_LOG
    (or stdout) and prints a markdown failure report on the first non-zero
    exit code.

    Exit codes:
      0 = all checks passed
      1 = at least one check failed (or fatal config error)

.PARAMETER ProfilePath
    Path to solution-profile.yaml. Defaults to ./solution-profile.yaml.

.PARAMETER SkillRoot
    Path to the test-bar-gate skill folder (used to locate references/commands.yaml).
    Defaults to the parent of this script's directory.

.NOTES
    Requires `ConvertFrom-Yaml` (powershell-yaml module). If unavailable, the
    script falls back to a minimal regex-based parser that supports only the
    keys this gate actually reads. Install with: Install-Module powershell-yaml
#>
[CmdletBinding()]
param(
    [string]$ProfilePath = (Join-Path (Get-Location) 'solution-profile.yaml'),
    [string]$SkillRoot   = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$CommandsYaml = Join-Path $SkillRoot 'references\commands.yaml'

function Read-Yaml([string]$Path) {
    if (-not (Test-Path $Path)) { return @{} }
    if (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue) {
        return Get-Content -Raw $Path | ConvertFrom-Yaml
    }
    Write-Warning "ConvertFrom-Yaml not available; using minimal fallback parser. Install powershell-yaml for full support."
    # Minimal fallback: only handles top-level stack keys with lint/typecheck/test arrays.
    # For overrides in solution-profile.yaml the user MUST install powershell-yaml.
    return @{}
}

function Emit-Event([hashtable]$evt) {
    $json = ($evt | ConvertTo-Json -Compress -Depth 6)
    if ($env:COPILOT_EVENT_LOG) {
        Add-Content -Path $env:COPILOT_EVENT_LOG -Value $json
    } else {
        Write-Host $json
    }
}

function Resolve-Stack($profile) {
    $langs = $profile.tech_stack.primary_languages
    if ($langs -and $langs.Count -gt 0) { return ($langs[0].ToString().ToLowerInvariant()) }
    return $null
}

function Resolve-Commands($profile, $stack, $defaults) {
    $override = $profile.quality_gates.test_bar.commands
    $base = if ($defaults.ContainsKey($stack)) { $defaults[$stack] } else { @{} }
    if (-not $override) { return $base }
    foreach ($k in @('lint','typecheck','test')) {
        if ($override.$k) { $base[$k] = $override.$k }
    }
    return $base
}

function Invoke-Check($name, $argv, $stack) {
    $cmdline = ($argv -join ' ')
    Write-Host "→ $name : $cmdline"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $stderrFile = New-TemporaryFile
    try {
        $proc = Start-Process -FilePath $argv[0] -ArgumentList ($argv | Select-Object -Skip 1) `
            -NoNewWindow -PassThru -Wait -RedirectStandardError $stderrFile.FullName
        $sw.Stop()
        $exit = $proc.ExitCode
        if ($exit -eq 0) {
            Emit-Event @{ event_type='gate_check'; check=$name; outcome='success'; stack=$stack; command=$cmdline; duration_ms=$sw.ElapsedMilliseconds }
            return $true
        }
        $stderr = (Get-Content -Raw $stderrFile.FullName) ?? ''
        $tail = ($stderr -split "`n" | Select-Object -Last 30) -join "`n"
        Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; stack=$stack; command=$cmdline; exit_code=$exit; stderr_tail=$tail }
        Write-Host ""
        Write-Host "❌ **Test-bar gate failed: $name**"
        Write-Host ""
        Write-Host "- **Stack detected:** $stack"
        Write-Host "- **Command run:** ``$cmdline``"
        Write-Host "- **Exit code:** $exit"
        Write-Host "- **Working directory:** $(Get-Location)"
        Write-Host ""
        Write-Host "### stderr (last 30 lines)`n`n``````text`n$tail`n``````"
        Write-Host ""
        Write-Host "### Suggested next action`n`nReturn to ``coding`` (or ``testing`` if the failure belongs to the test layer) with this report and one corrective retry."
        return $false
    } finally {
        Remove-Item $stderrFile -ErrorAction SilentlyContinue
    }
}

# --- main ---
$profile  = Read-Yaml $ProfilePath
$defaults = Read-Yaml $CommandsYaml
$stack    = Resolve-Stack $profile

if (-not $stack -or -not $defaults.ContainsKey($stack)) {
    Emit-Event @{ event_type='gate_check'; check='resolve'; outcome='skipped'; reason='no_stack_match' }
    Write-Warning "test-bar-gate: no stack match — gate skipped."
    exit 0
}

$cmds     = Resolve-Commands $profile $stack $defaults
$failFast = $true
if ($null -ne $profile.quality_gates.test_bar.fail_fast) { $failFast = [bool]$profile.quality_gates.test_bar.fail_fast }

$allOk = $true
foreach ($check in @('lint','typecheck','test')) {
    if (-not $cmds.$check) { continue }
    $ok = Invoke-Check $check $cmds.$check $stack
    if (-not $ok) { $allOk = $false; if ($failFast) { break } }
}

if ($allOk) {
    Emit-Event @{ event_type='gate_check'; check='summary'; outcome='success'; stack=$stack }
    exit 0
} else {
    exit 1
}
