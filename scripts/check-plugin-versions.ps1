#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Fails when a plugin's files changed without its version moving, and when a version
    is inconsistent between its manifest and the marketplace listing.

.DESCRIPTION
    The version is the delivery mechanism: an installed plugin picks up nothing until it
    moves, so an unbumped fix ships to nobody. Nothing enforced this and it was missed
    twice (PR #3 left four plugins at 0.1.0 with broken skill references; PR #7 shipped
    three changed plugins before the omission was noticed).

    Two independent checks:

      consistency  Every plugin.json version equals its marketplace plugins[] entry, and
                   metadata.version tracks agile-agents-core. Pure file read, no git, so it
                   also runs locally and on push.

      bump         Every plugin with changed files under plugins/<name>/ has a version
                   greater than at -BaseRef. Needs git history, so CI passes the PR base.

    Bumping is per PR, not per commit, which is why the bump check compares against the
    merge base rather than the previous commit.

.PARAMETER BaseRef
    Ref to compare against for the bump check (e.g. 'origin/main'). Omit to run only the
    consistency check.

.EXAMPLE
    ./scripts/check-plugin-versions.ps1
    ./scripts/check-plugin-versions.ps1 -BaseRef origin/main
#>
[CmdletBinding()]
param(
    [string] $BaseRef,
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$failures = [System.Collections.Generic.List[string]]::new()

$marketplacePath = Join-Path $RepoRoot '.github/plugin/marketplace.json'
if (-not (Test-Path $marketplacePath)) {
    Write-Host "marketplace.json not found at $marketplacePath" -ForegroundColor Red
    exit 1
}
$marketplace = Get-Content $marketplacePath -Raw | ConvertFrom-Json

function Get-ManifestPath([string] $name) {
    Join-Path $RepoRoot "plugins/$name/.github/plugin/plugin.json"
}

function Get-ManifestVersion([string] $name) {
    $p = Get-ManifestPath $name
    if (-not (Test-Path $p)) { return $null }
    (Get-Content $p -Raw | ConvertFrom-Json).version
}

# A pre-release suffix (0.4.0-rc1) is not [version]-parseable; compare those as strings so
# the check degrades to "must differ" rather than throwing.
function Compare-Version([string] $old, [string] $new) {
    $o = $null; $n = $null
    if ([version]::TryParse($old, [ref] $o) -and [version]::TryParse($new, [ref] $n)) {
        return $n.CompareTo($o)
    }
    return $(if ($old -eq $new) { 0 } else { 1 })
}

# ---------------------------------------------------------------- consistency

$pluginDirs = Get-ChildItem (Join-Path $RepoRoot 'plugins') -Directory |
    Where-Object { Test-Path (Get-ManifestPath $_.Name) } |
    Select-Object -ExpandProperty Name

$listed = @($marketplace.plugins | Select-Object -ExpandProperty source)

foreach ($name in $pluginDirs) {
    if ($name -notin $listed) {
        $failures.Add("plugins/$name has a manifest but no plugins[] entry in marketplace.json.")
    }
}

foreach ($entry in $marketplace.plugins) {
    $name = $entry.source
    $manifestVersion = Get-ManifestVersion $name
    if ($null -eq $manifestVersion) {
        $failures.Add("marketplace.json lists '$name', but plugins/$name/.github/plugin/plugin.json does not exist.")
        continue
    }
    if ($entry.version -ne $manifestVersion) {
        $failures.Add("version mismatch for '$name': plugin.json says '$manifestVersion', marketplace.json says '$($entry.version)'. Bump both.")
    }
}

$coreVersion = Get-ManifestVersion 'agile-agents-core'
if ($coreVersion -and $marketplace.metadata.version -ne $coreVersion) {
    $failures.Add("marketplace.json metadata.version is '$($marketplace.metadata.version)' but agile-agents-core is '$coreVersion'. metadata.version tracks core.")
}

# ----------------------------------------------------------------------- bump

if ($BaseRef) {
    Push-Location $RepoRoot
    try {
        $changed = @(git diff --name-only "$BaseRef...HEAD" -- 'plugins/')
        if ($LASTEXITCODE -ne 0) {
            Write-Host "git diff against '$BaseRef' failed. Fetch the base ref (actions/checkout needs fetch-depth: 0)." -ForegroundColor Red
            exit 1
        }

        # plugins/VENDORED.md and friends sit directly under plugins/ and belong to no
        # plugin; requiring the trailing slash skips them.
        $touched = $changed |
            ForEach-Object { if ($_ -match '^plugins/([^/]+)/') { $Matches[1] } } |
            Sort-Object -Unique

        foreach ($name in $touched) {
            if ($name -notin $pluginDirs) { continue }   # deleted, or not a plugin

            $baseJson = git show "${BaseRef}:plugins/$name/.github/plugin/plugin.json" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $baseJson) {
                # New in this PR: its initial version is the bump.
                continue
            }

            $baseVersion = ($baseJson | ConvertFrom-Json).version
            $headVersion = Get-ManifestVersion $name
            $cmp = Compare-Version $baseVersion $headVersion

            if ($cmp -eq 0) {
                $files = @($changed | Where-Object { $_ -like "plugins/$name/*" })
                $sample = ($files | Select-Object -First 3) -join ', '
                if ($files.Count -gt 3) { $sample += ", +$($files.Count - 3) more" }
                $failures.Add("plugins/$name changed but its version is still '$baseVersion' ($sample). Bump it in plugin.json and in its marketplace.json plugins[] entry.")
            }
            elseif ($cmp -lt 0) {
                $failures.Add("plugins/$name went backwards: '$baseVersion' -> '$headVersion'.")
            }
        }

        # The inverse error: a version moved with no content behind it, which publishes a
        # release identical to the last one.
        foreach ($name in $pluginDirs) {
            if ($name -in $touched) { continue }
            $baseJson = git show "${BaseRef}:plugins/$name/.github/plugin/plugin.json" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $baseJson) { continue }
            if (($baseJson | ConvertFrom-Json).version -ne (Get-ManifestVersion $name)) {
                $failures.Add("plugins/$name was bumped but none of its files changed. Leave untouched plugins alone.")
            }
        }
    }
    finally { Pop-Location }
}

# --------------------------------------------------------------------- report

if ($failures.Count) {
    Write-Host "Plugin version check failed:`n" -ForegroundColor Red
    $failures | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "`nBump every plugin whose files changed, in the same PR, in both its"
    Write-Host "plugins/<name>/.github/plugin/plugin.json and its marketplace.json entry."
    Write-Host "Minor for behaviour changes, patch for repairs. metadata.version tracks core."
    exit 1
}

$scope = if ($BaseRef) { "consistent, and bumped where changed vs $BaseRef" } else { 'consistent (bump check skipped: no -BaseRef)' }
Write-Host "Plugin version check passed: $($pluginDirs.Count) plugins $scope." -ForegroundColor Green
