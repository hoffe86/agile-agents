<#
.SYNOPSIS
    Detects drift between the vendored skills in this repo and their upstream originals.

.DESCRIPTION
    Reads the skill -> plugin -> upstream table in plugins/VENDORED.md, fetches each upstream
    SKILL.md, and compares it with the local copy.

    Deliberately deterministic: a plain fetch-and-diff, no model, no MCP server, no Docker. The
    question "did upstream change?" has one right answer, so it should not cost tokens or vary
    between runs. Judging whether a change is worth taking is the `capability-scout` agent's job.

    Only locally owned `metadata.applies_to` is ignored, within frontmatter.
    An annotation-only metadata wrapper is removed only when absent upstream.
    Upstream scope collisions and malformed YAML fail comparison. Other metadata,
    comments, native fields, formatting and body differences remain real drift.

.PARAMETER RepoRoot
    Repository root. Defaults to the parent of this script's directory.

.PARAMETER Skill
    Check a single skill by name instead of every vendored skill.

.PARAMETER ShowDiff
    Print the first differing lines for each drifted skill.

.NOTES
    Exit codes: 0 = all in sync (or drift found and -WarnOnly), 1 = drift found,
    2 = fetch/comparison failure (including upstream annotation collisions).
    Requires network access to raw.githubusercontent.com and Python with PyYAML
    (the same dependency as check-skill-frontmatter.py).
#>
[CmdletBinding()]
param(
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string] $Skill,
    [switch] $ShowDiff,
    [switch] $WarnOnly
)

$ErrorActionPreference = 'Stop'
$vendoredMd = Join-Path $RepoRoot 'plugins/VENDORED.md'
if (-not (Test-Path $vendoredMd)) { Write-Host "Not found: $vendoredMd" -ForegroundColor Red; exit 2 }

# Rows look like: | <skill> | `<plugin>` | <upstream url> |
$rows = Get-Content $vendoredMd |
    Select-String -Pattern '^\|\s*([a-z0-9-]+)\s*\|\s*`([^`]+)`\s*\|\s*(https?://\S+)\s*\|' |
    ForEach-Object {
        [PSCustomObject]@{
            Skill    = $_.Matches[0].Groups[1].Value
            Plugin   = $_.Matches[0].Groups[2].Value
            Upstream = $_.Matches[0].Groups[3].Value
        }
    }

if ($Skill) { $rows = @($rows | Where-Object { $_.Skill -eq $Skill }) }
if (-not $rows -or $rows.Count -eq 0) { Write-Host "No vendored skills matched." -ForegroundColor Yellow; exit 2 }

function Get-ComparablePair([string] $localText, [string] $upstreamText) {
    $request = @{ local = $localText; upstream = $upstreamText } | ConvertTo-Json -Compress
    $result = $request | & python -X utf8 (Join-Path $PSScriptRoot 'normalize-vendored-skill.py')
    if ($LASTEXITCODE -ne 0) { throw 'Scope normalization failed; see diagnostic above.' }
    $result | ConvertFrom-Json
}

$inSync = @(); $drifted = @(); $failed = @(); $missing = @()

foreach ($row in $rows) {
    $local = Join-Path $RepoRoot "plugins/$($row.Plugin)/skills/$($row.Skill)/SKILL.md"
    if (-not (Test-Path $local)) { $missing += $row; continue }

    # tree/main/skills/<name> -> raw .../main/skills/<name>/SKILL.md
    $raw = ($row.Upstream -replace '/tree/', '/') -replace '^https://github\.com/', 'https://raw.githubusercontent.com/'
    $raw = "$raw/SKILL.md"

    try {
        $remote = (Invoke-WebRequest -Uri $raw -UseBasicParsing -TimeoutSec 30).Content
    } catch {
        $failed += [PSCustomObject]@{ Skill = $row.Skill; Url = $raw; Error = $_.Exception.Message }
        continue
    }

    try {
        $pair = Get-ComparablePair (Get-Content $local -Raw -Encoding utf8) $remote
    } catch {
        $failed += [PSCustomObject]@{ Skill = $row.Skill; Url = $raw; Error = $_.Exception.Message }
        continue
    }
    $l = $pair.local -split "`n"
    $r = $pair.upstream -split "`n"

    if (($l -join "`n") -eq ($r -join "`n")) {
        $inSync += $row
    } else {
        $diff = Compare-Object $l $r | Select-Object -First 6
        $drifted += [PSCustomObject]@{ Skill = $row.Skill; Plugin = $row.Plugin; Url = $raw; Diff = $diff }
    }
}

"Vendored skill drift — $($rows.Count) checked"
""
if ($inSync)  { "  in sync   : $($inSync.Count)" }
if ($drifted) { "  DRIFTED   : $($drifted.Count)" }
if ($missing) { "  missing   : $($missing.Count)  (listed in VENDORED.md, absent on disk)" }
if ($failed)  { "  failed    : $($failed.Count)  (fetch or comparison)" }
""

foreach ($d in $drifted) {
    Write-Host "  ~ $($d.Skill)  [$($d.Plugin)]" -ForegroundColor Yellow
    Write-Host "      $($d.Url)"
    if ($ShowDiff) {
        foreach ($line in $d.Diff) {
            $marker = if ($line.SideIndicator -eq '=>') { 'upstream' } else { 'local   ' }
            $text = $line.InputObject
            if ($text.Length -gt 100) { $text = $text.Substring(0, 100) + '…' }
            Write-Host "      $marker | $text" -ForegroundColor DarkGray
        }
    }
}
foreach ($m in $missing) { Write-Host "  ! $($m.Skill) — not found at plugins/$($m.Plugin)/skills/$($m.Skill)/SKILL.md" -ForegroundColor Red }
foreach ($f in $failed)  { Write-Host "  ? $($f.Skill) — check failed: $($f.Error)" -ForegroundColor DarkYellow }

# A malformed input or upstream collision cannot be waived as ordinary drift.
if ($failed) { exit 2 }

if ($drifted -or $missing) {
    ""
    "Drift is not automatically a defect: upstream may have changed in ways this suite does not want."
    "Hand the list to the ``capability-scout`` agent to decide per skill, then re-sync the ones worth taking."
    "Re-run with -ShowDiff to see what moved."
    if ($WarnOnly) { exit 0 }
    exit 1
}

"All vendored skills match upstream."
exit 0
