<#
.SYNOPSIS
    Test-bar gate runner (PowerShell).

.DESCRIPTION
    Runs the checks declared under `quality_gates.test_bar` in solution-profile.yaml,
    in order, fail-fast by default:

        lint -> typecheck -> unit_test -> integration_test -> coverage -> mutation -> smoke

    A check runs when it is enabled AND resolves to a command. lint / typecheck /
    unit_test fall back to the per-stack palette in references/commands.yaml; the
    rest run only when the profile gives them an explicit command. The smoke slot
    is separate: it comes from `testing.smoke` and starts the app, polls a URL,
    and always stops the process again.

    Emits gate_check events to $env:COPILOT_EVENT_LOG (or stdout) and prints a
    markdown failure report on the first failing check.

    Exit codes:
      0 = all checks passed, or the gate was skipped
      1 = at least one check failed
      2 = fatal config error

.PARAMETER ProfilePath
    Path to solution-profile.yaml. Defaults to ./solution-profile.yaml.

.PARAMETER SkillRoot
    Path to the test-bar-gate skill folder (used to locate references/commands.yaml).
    Defaults to the parent of this script's directory.

.PARAMETER SmokeCommand
    Start command for the smoke slot, overriding testing.smoke.command. Carries the
    entry point the caller discovered when the profile does not declare one — see
    references/startup-discovery.md.

.PARAMETER SmokeUrl
    Health URL for the smoke slot, overriding testing.smoke.url.

.NOTES
    Requires `ConvertFrom-Yaml` (powershell-yaml module) to read the profile.
    Install with: Install-Module powershell-yaml
#>
[CmdletBinding()]
param(
    [string]$ProfilePath = (Join-Path (Get-Location) 'solution-profile.yaml'),
    [string]$SkillRoot   = (Split-Path -Parent $PSScriptRoot)
    , [string]$SmokeCommand = ''
    , [string]$SmokeUrl     = ''
)

$ErrorActionPreference = 'Stop'
$CommandsYaml = Join-Path $SkillRoot 'references/commands.yaml'

# Checks in execution order. Only those flagged $true may fall back to the palette.
$CheckOrder = [ordered]@{
    lint             = $true
    typecheck        = $true
    unit_test        = $true
    integration_test = $false
    coverage         = $false
    mutation         = $false
}
# Checks that are on unless the profile says otherwise.
$DefaultEnabled = @{ lint = $true; typecheck = $true; unit_test = $true }

function Read-Yaml([string]$Path, [switch]$Required) {
    if (-not (Test-Path $Path)) {
        if ($Required) { throw "Required YAML file not found: $Path" }
        return @{}
    }
    if (-not (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
        throw "ConvertFrom-Yaml is unavailable. Install it with: Install-Module powershell-yaml"
    }
    $parsed = Get-Content -Raw $Path | ConvertFrom-Yaml
    if ($null -eq $parsed) { return @{} }
    return $parsed
}

function Emit-Event([hashtable]$evt) {
    $json = ($evt | ConvertTo-Json -Compress -Depth 6)
    if ($env:COPILOT_EVENT_LOG) {
        Add-Content -Path $env:COPILOT_EVENT_LOG -Value $json
    } else {
        Write-Host $json
    }
}

# Reads a nested key without throwing when an intermediate level is absent.
function Get-Node($root, [string[]]$Path) {
    $node = $root
    foreach ($segment in $Path) {
        if ($null -eq $node) { return $null }
        if ($node -is [System.Collections.IDictionary]) {
            if (-not $node.Contains($segment)) { return $null }
            $node = $node[$segment]
        } else {
            $prop = $node.PSObject.Properties[$segment]
            if (-not $prop) { return $null }
            $node = $prop.Value
        }
    }
    return $node
}

# A command may be a list (["ruff", "check", "."]) or a string ("ruff check .").
function ConvertTo-Argv($value) {
    if ($null -eq $value) { return @() }
    if ($value -is [string]) {
        if ([string]::IsNullOrWhiteSpace($value)) { return @() }
        return @($value -split '\s+' | Where-Object { $_ })
    }
    return @($value | ForEach-Object { "$_" } | Where-Object { $_ })
}

function Resolve-Stacks($profile) {
    $declared = ConvertTo-Argv (Get-Node $profile @('quality_gates', 'test_bar', 'stacks'))
    if ($declared.Count -gt 0) { return @($declared | ForEach-Object { $_.ToLowerInvariant() }) }

    $langs = Get-Node $profile @('tech_stack', 'primary_languages')
    if ($langs) {
        foreach ($lang in @($langs)) {
            # primary_languages entries may be plain strings or { name: ... } maps.
            $name = if ($lang -is [System.Collections.IDictionary]) { $lang['name'] } else { $lang }
            if ($name) { return @("$name".ToLowerInvariant()) }
        }
    }
    return @()
}

# Falls back to a lint/build tool hint when the language name is not a palette key.
function Resolve-StackAlias([string]$stack, $profile, $defaults) {
    if ($stack -and $defaults.Contains($stack)) { return $stack }
    $hints = @()
    $hints += ConvertTo-Argv (Get-Node $profile @('tech_stack', 'lint_format_tools'))
    $hints += ConvertTo-Argv (Get-Node $profile @('tech_stack', 'build_tools'))
    $map = [ordered]@{
        eslint = 'typescript'; prettier = 'typescript'; tsc = 'typescript'; biome = 'typescript'
        ruff   = 'python';     black    = 'python';     mypy = 'python';    pyright = 'python'
        golangci = 'go';       gofmt    = 'go'
        dotnet = 'csharp'
    }
    foreach ($hint in $hints) {
        $key = "$hint".ToLowerInvariant()
        foreach ($known in $map.Keys) {
            if ($key -like "*$known*" -and $defaults.Contains($map[$known])) { return $map[$known] }
        }
    }
    return $null
}

function Resolve-Check($profile, [string]$check, [string]$stack, $defaults) {
    $node = Get-Node $profile @('quality_gates', 'test_bar', $check)

    $enabled = $DefaultEnabled.ContainsKey($check)
    $explicit = Get-Node $node @('enabled')
    if ($null -ne $explicit) { $enabled = [bool]$explicit }
    if (-not $enabled) { return @{ Enabled = $false; Argv = @() } }

    $argv = ConvertTo-Argv (Get-Node $node @('command'))
    if ($argv.Count -eq 0 -and $CheckOrder[$check] -and $stack) {
        $argv = ConvertTo-Argv (Get-Node $defaults @($stack, $check))
    }
    return @{ Enabled = $true; Argv = $argv }
}

function Write-FailureReport([string]$name, [string]$stack, [string]$cmdline, $exitCode, [string]$tail, [string]$reason) {
    $shown = if ($stack) { $stack } else { '(none - commands came from the profile)' }
    Write-Host ""
    Write-Host "**Test-bar gate failed: $name**"
    Write-Host ""
    Write-Host "- **Stack detected:** $shown"
    Write-Host "- **Command run:** ``$cmdline``"
    Write-Host "- **Exit code:** $exitCode"
    if ($reason) { Write-Host "- **Reason:** $reason" }
    Write-Host "- **Working directory:** $(Get-Location)"
    Write-Host ""
    Write-Host "### stderr (last 30 lines)`n`n``````text`n$tail`n``````"
    Write-Host ""
    Write-Host "### Suggested next action`n`nReturn to ``coding`` (or ``infrastructure`` when the diff is IaC-only) with this report and one corrective retry."
}

function Invoke-Check([string]$name, [string[]]$argv, [string]$stack) {
    $cmdline = ($argv -join ' ')
    Write-Host "-> $name : $cmdline"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $stderrFile = New-TemporaryFile
    try {
        try {
            $proc = Start-Process -FilePath $argv[0] -ArgumentList ($argv | Select-Object -Skip 1) `
                -NoNewWindow -PassThru -Wait -RedirectStandardError $stderrFile.FullName
        } catch {
            # An uninstalled toolchain is the most common gate failure on a fresh
            # machine. Report it through the normal contract instead of throwing.
            $sw.Stop()
            $msg = "command not found: $($argv[0])"
            Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; stack=$stack; command=$cmdline; exit_code=127; stderr_tail=$msg; reason='command_not_found' }
            Write-FailureReport $name $stack $cmdline 127 $msg 'command_not_found'
            return $false
        }
        $sw.Stop()
        $exit = $proc.ExitCode
        if ($exit -eq 0) {
            Emit-Event @{ event_type='gate_check'; check=$name; outcome='success'; stack=$stack; command=$cmdline; duration_ms=$sw.ElapsedMilliseconds }
            return $true
        }
        $stderr = (Get-Content -Raw $stderrFile.FullName)
        if ($null -eq $stderr) { $stderr = '' }
        $tail = ($stderr -split "`n" | Select-Object -Last 30) -join "`n"
        Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; stack=$stack; command=$cmdline; exit_code=$exit; stderr_tail=$tail }
        Write-FailureReport $name $stack $cmdline $exit $tail
        return $false
    } finally {
        Remove-Item $stderrFile -ErrorAction SilentlyContinue
    }
}

# Opt-in "does the app come up?" slot. Always stops the process it started.
function Invoke-Smoke($profile, [string]$stack) {
    # CLI overrides win: they carry the entry point the agent discovered when the
    # profile does not declare one (see references/startup-discovery.md).
    if ($SmokeCommand) {
        $argv = ConvertTo-Argv $SmokeCommand
        $url  = $SmokeUrl
    }
    else {
        $argv = ConvertTo-Argv (Get-Node $profile @('testing', 'smoke', 'command'))
        $url  = Get-Node $profile @('testing', 'smoke', 'url')
        if (-not $url) { $url = $SmokeUrl }
    }
    if ($argv.Count -eq 0 -or -not $url) {
        # Not silently fine: a runnable project still has to be started. The script
        # cannot inspect a repo to work out how, so it reports that the caller must
        # resolve the entry point and re-invoke with -SmokeCommand / -SmokeUrl.
        Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='skipped'; reason='needs_discovery' }
        Write-Warning "smoke: not configured - resolve the entry point (references/startup-discovery.md) and re-run with -SmokeCommand/-SmokeUrl, or record not_applicable/undetermined"
        return $true
    }
    $timeout = Get-Node $profile @('testing', 'smoke', 'timeout_s')
    if (-not $timeout) { $timeout = 60 }

    $cmdline = ($argv -join ' ')
    Write-Host "-> smoke : $cmdline (polling $url, timeout ${timeout}s)"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $outFile = New-TemporaryFile
    $errFile = New-TemporaryFile
    $proc = $null
    try {
        try {
            $proc = Start-Process -FilePath $argv[0] -ArgumentList ($argv | Select-Object -Skip 1) `
                -NoNewWindow -PassThru -RedirectStandardOutput $outFile.FullName -RedirectStandardError $errFile.FullName
        } catch {
            $sw.Stop()
            $msg = "command not found: $($argv[0])"
            Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='fail'; stack=$stack; command=$cmdline; exit_code=127; stderr_tail=$msg; reason='command_not_found' }
            Write-FailureReport 'smoke' $stack $cmdline 127 $msg 'command_not_found'
            return $false
        }
        $deadline = (Get-Date).AddSeconds([int]$timeout)
        $up = $false
        while ((Get-Date) -lt $deadline) {
            if ($proc.HasExited) { break }
            try {
                $resp = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing -SkipHttpErrorCheck
                if ([int]$resp.StatusCode -lt 500) { $up = $true; break }
            } catch {
                # Not listening yet - keep polling until the deadline.
            }
            Start-Sleep -Seconds 2
        }
        $sw.Stop()
        if ($up) {
            Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='success'; stack=$stack; command=$cmdline; duration_ms=$sw.ElapsedMilliseconds }
            return $true
        }
        $combined = @()
        foreach ($f in @($outFile, $errFile)) {
            $c = (Get-Content -Raw $f.FullName)
            if ($c) { $combined += $c }
        }
        $tail = (($combined -join "`n") -split "`n" | Select-Object -Last 20) -join "`n"
        $reason = if ($proc.HasExited) { "process exited with $($proc.ExitCode)" } else { "no response within ${timeout}s" }
        Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='fail'; stack=$stack; command=$cmdline; exit_code=1; stderr_tail=$tail; reason=$reason }
        Write-FailureReport 'smoke' $stack $cmdline 1 $tail $reason
        return $false
    } finally {
        # A leaked listener holds the port and breaks the next run.
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
    }
}

# --- main ---
try {
    $profile  = Read-Yaml $ProfilePath
    $defaults = Read-Yaml $CommandsYaml -Required
} catch {
    Write-Error $_.Exception.Message
    exit 2
}

$gateEnabled = Get-Node $profile @('quality_gates', 'test_bar', 'enabled')
if ($null -ne $gateEnabled -and -not [bool]$gateEnabled) {
    Emit-Event @{ event_type='gate_check'; check='resolve'; outcome='skipped'; reason='disabled_by_profile' }
    Write-Host "test-bar-gate: disabled by profile - gate skipped."
    exit 0
}

$stacks = @()
foreach ($candidate in (Resolve-Stacks $profile)) {
    $resolved = Resolve-StackAlias $candidate $profile $defaults
    if ($resolved -and $stacks -notcontains $resolved) { $stacks += $resolved }
}

$failFast = $true
$ff = Get-Node $profile @('quality_gates', 'test_bar', 'fail_fast')
if ($null -ne $ff) { $failFast = [bool]$ff }

# A profile-supplied command needs no stack, so an unmatched stack is not fatal
# on its own - we only skip when nothing at all resolved to a command.
if ($stacks.Count -eq 0) { $stacks = @('') }

$allOk = $true
$ranAnything = $false
:outer foreach ($stack in $stacks) {
    foreach ($check in $CheckOrder.Keys) {
        $resolved = Resolve-Check $profile $check $stack $defaults
        if (-not $resolved.Enabled -or $resolved.Argv.Count -eq 0) { continue }
        $ranAnything = $true
        if (-not (Invoke-Check $check $resolved.Argv $stack)) {
            $allOk = $false
            if ($failFast) { break outer }
        }
    }
}

if (-not $ranAnything) {
    Emit-Event @{ event_type='gate_check'; check='resolve'; outcome='skipped'; reason='no_stack_match' }
    Write-Warning "test-bar-gate: no stack match and no explicit commands - gate skipped."
    exit 0
}

if ($allOk -or -not $failFast) {
    if (-not (Invoke-Smoke $profile ($stacks[0]))) { $allOk = $false }
}

if ($allOk) {
    Emit-Event @{ event_type='gate_check'; check='summary'; outcome='success'; stack=(($stacks | Where-Object { $_ }) -join ',') }
    exit 0
}
exit 1
