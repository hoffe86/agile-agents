<#
.SYNOPSIS
    Detects drift between the vendored skills in this repo and their upstream originals.

.DESCRIPTION
    Reads the skill -> plugin -> upstream table in plugins/VENDORED.md, fetches each upstream
    SKILL.md, and compares it with the local copy.

    Deliberately deterministic: a plain fetch-and-diff, no model, no MCP server, no Docker. The
    question "did upstream change?" has one right answer, so it should not cost tokens or vary
    between runs. Judging whether a change is worth taking is the `skill-scout` agent's job.

    The one sanctioned local modification -- the `applies_to:` frontmatter line, which upstream
    has no equivalent for (see plugins/VENDORED.md) -- is ignored when comparing. Any other
    difference is real drift.

.PARAMETER RepoRoot
    Repository root. Defaults to the parent of this script's directory.

.PARAMETER Skill
    Check a single skill by name instead of every vendored skill.

.PARAMETER ShowDiff
    Print the first differing lines for each drifted skill.

.NOTES
    Exit codes: 0 = all in sync (or drift found and -WarnOnly), 1 = drift found, 2 = fetch failure.
    Requires network access to raw.githubusercontent.com.
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

# Strip the locally-added applies_to line so it never reads as drift, and normalise line
# endings -- .gitattributes keeps the repo on LF, but a fetch may hand back CRLF.
function Get-Comparable([string] $text) {
    $lines = ($text -replace "`r`n", "`n") -split "`n" |
        Where-Object { $_ -notmatch '^applies_to:\s' } |
        ForEach-Object { $_.TrimEnd() }
    # Drop trailing blank lines: a fetched file and a written one routinely differ by a final
    # newline, which is not drift and would otherwise flag every skill the day it is vendored.
    $end = $lines.Count - 1
    while ($end -ge 0 -and [string]::IsNullOrWhiteSpace($lines[$end])) { $end-- }
    if ($end -lt 0) { return @() }
    $lines[0..$end]
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

    $l = Get-Comparable (Get-Content $local -Raw)
    $r = Get-Comparable $remote

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
if ($failed)  { "  fetch fail: $($failed.Count)" }
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
foreach ($f in $failed)  { Write-Host "  ? $($f.Skill) — fetch failed: $($f.Error)" -ForegroundColor DarkYellow }

if ($drifted -or $missing) {
    ""
    "Drift is not automatically a defect: upstream may have changed in ways this suite does not want."
    "Hand the list to the ``skill-scout`` agent to decide per skill, then re-sync the ones worth taking."
    "Re-run with -ShowDiff to see what moved."
    if ($WarnOnly) { exit 0 }
    exit 1
}
if ($failed) { exit 2 }

"All vendored skills match upstream."
exit 0
