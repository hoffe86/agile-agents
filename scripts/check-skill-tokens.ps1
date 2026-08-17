<#
.SYNOPSIS
    S0 skill checks — token ratchet and eval-coverage report across every plugin.

.DESCRIPTION
    Waza's `paths.skills` is a single directory, but this repo is a marketplace
    with skills under `plugins/*/skills`. Every Waza invocation therefore has to
    be handed the plugin directories explicitly; this wrapper does that discovery
    so a local run and the CI run are the same command.

    Free and offline: no model is called and no Copilot token is needed, which is
    why S0 is allowed to gate (same reasoning as the L0 trajectory eval, ADR 0008).

    Token limits come from .waza.yaml and are a **ratchet set at today's measured
    cost** — they exist to fail a regression, not to bless the current size. Do not
    raise one to make this pass.

.PARAMETER WazaPath
    Path to the waza binary. Defaults to `waza` on PATH.

.PARAMETER SkipCoverage
    Skip the (informational) eval-coverage report.
#>
[CmdletBinding()]
param(
    [string]$WazaPath = 'waza',
    [switch]$SkipCoverage
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repoRoot
try {
    $skillDirs = Get-ChildItem (Join-Path $repoRoot 'plugins') -Directory |
        ForEach-Object { "plugins/$($_.Name)/skills" } |
        Where-Object { Test-Path (Join-Path $repoRoot $_) }

    if (-not $skillDirs) { Write-Error 'No plugins/*/skills directories found.'; exit 2 }
    Write-Host "Scanning $($skillDirs.Count) plugin skill directories."

    # --- Token ratchet (gating) ----------------------------------------------
    $raw = & $WazaPath tokens check @skillDirs --format json --no-update-check 2>&1 | Out-String
    try { $result = $raw | ConvertFrom-Json } catch {
        Write-Error "waza tokens check did not return JSON:`n$raw"; exit 2
    }

    # Only SKILL.md is budgeted; reference/ material is not loaded on trigger.
    $skills = @($result.results | Where-Object { $_.file -like '*SKILL.md' })
    $over = @($skills | Where-Object { $_.exceeded })

    Write-Host ("SKILL.md files: {0}   over budget: {1}" -f $skills.Count, $over.Count)

    if ($over.Count -gt 0) {
        Write-Host ''
        Write-Host 'Token budget exceeded:'
        foreach ($s in $over | Sort-Object tokens -Descending) {
            Write-Host ("  {0,6} / {1,-6} {2}" -f $s.tokens, $s.limit, $s.file)
        }
        Write-Host ''
        Write-Host 'A skill body is loaded into context when it triggers, so this is recurring cost.'
        Write-Host 'Trim the skill, or move detail into references/ (loaded on demand, not on trigger).'
        Write-Host 'Raising the limit in .waza.yaml to go green is metric gaming — see engineering-judgement.'
        exit 1
    }

    # --- Eval coverage (informational until suites exist) ---------------------
    if (-not $SkipCoverage) {
        $covArgs = @('coverage', '--no-update-check', '-f', 'json')
        foreach ($d in $skillDirs) { $covArgs += @('--path', $d) }
        # Skills live under plugins/*/skills but their eval suites live at repo-root
        # evals/<skill>/ — without this the scan finds every skill and no suite, and
        # reports a flat 0%.
        if (Test-Path (Join-Path $repoRoot 'evals')) { $covArgs += @('--path', 'evals') }

        $covRaw = & $WazaPath @covArgs 2>&1 | Out-String
        try {
            $cov = $covRaw | ConvertFrom-Json
            $withSuite = [int]$cov.covered + [int]$cov.partial
            Write-Host ''
            Write-Host ("Eval coverage: {0}/{1} skills have an eval suite ({2} full, {3} partial)." -f
                $withSuite, $cov.total_skills, $cov.covered, $cov.partial)
            Write-Host '  (informational — S1/S2 tiers are being built out; see docs/adr/0014)'
        } catch {
            Write-Host "Coverage report unavailable (non-fatal): $covRaw"
        }
    }

    Write-Host ''
    Write-Host 'S0 skill checks passed.'
    exit 0
}
finally { Pop-Location }
