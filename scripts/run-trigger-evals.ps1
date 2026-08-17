<#
.SYNOPSIS
    S0 routing baseline — run every trigger-accuracy eval and summarise.

.DESCRIPTION
    The `trigger` grader is a pure offline heuristic, so this calls no model and
    costs nothing; it belongs to the same free tier as the token ratchet.

    **Reports, does not gate.** The 0.6 threshold is Waza's default and has not been
    calibrated against this repo's description style, so a low score here is a
    finding to investigate, not a build to fail. Do not "fix" a score by rewriting a
    description to please the heuristic — that is the metric gaming ADR 0014 and
    `engineering-judgement` §7 both warn about.
#>
[CmdletBinding()]
param(
    [string]$WazaPath = 'waza',
    [switch]$FailOnRegression
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repoRoot
try {
    $evalFiles = Get-ChildItem (Join-Path $repoRoot 'evals') -Filter 'eval.yaml' -Recurse -ErrorAction SilentlyContinue
    if (-not $evalFiles) { Write-Host 'No eval suites found under evals/.'; exit 0 }

    $rows = @()
    foreach ($f in $evalFiles | Sort-Object FullName) {
        $rel = $f.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
        $skill = Split-Path (Split-Path $f.FullName -Parent) -Leaf
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("waza-{0}.json" -f $skill)

        # Structured results rather than scraping the console: the per-task name and
        # its score are printed on separate lines, which is easy to mis-pair.
        & $WazaPath run $rel -o $tmp --no-update-check 2>&1 | Out-Null
        if (-not (Test-Path $tmp)) { Write-Host "  (no results for $skill)"; continue }

        $res = Get-Content $tmp -Raw | ConvertFrom-Json
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue

        foreach ($t in $res.tasks) {
            $rows += [pscustomobject]@{
                Skill  = $skill
                Task   = $t.display_name
                Kind   = if ($t.test_id -match 'negative') { 'negative' } else { 'positive' }
                Score  = [double]$t.stats.avg_score
                Passed = ($t.status -eq 'passed')
            }
        }
    }

    if (-not $rows) { Write-Host 'No task results parsed — check waza output format.'; exit 2 }

    Write-Host ''
    Write-Host 'Routing (trigger-accuracy) baseline — offline heuristic, no model calls'
    Write-Host ('=' * 78)
    foreach ($g in $rows | Group-Object Skill | Sort-Object Name) {
        $pass = @($g.Group | Where-Object Passed).Count
        Write-Host ''
        Write-Host ("{0}  —  {1}/{2} correct" -f $g.Name, $pass, $g.Group.Count)
        foreach ($r in $g.Group | Sort-Object Kind, Task) {
            $mark = if ($r.Passed) { 'ok  ' } else { 'MISS' }
            Write-Host ("   {0}  {1,-4:N2}  [{2,-8}] {3}" -f $mark, $r.Score, $r.Kind, $r.Task)
        }
    }

    $total = $rows.Count
    $ok = @($rows | Where-Object Passed).Count
    $posMiss = @($rows | Where-Object { -not $_.Passed -and $_.Kind -eq 'positive' })
    $negMiss = @($rows | Where-Object { -not $_.Passed -and $_.Kind -eq 'negative' })

    Write-Host ''
    Write-Host ('-' * 78)
    Write-Host ("Overall: {0}/{1} correct ({2:N0}%)" -f $ok, $total, (100.0 * $ok / $total))
    Write-Host ("  missed triggers (skill would NOT fire when it should): {0}" -f $posMiss.Count)
    Write-Host ("  false triggers  (skill WOULD fire when it shouldn't):  {0}" -f $negMiss.Count)
    Write-Host 'Informational — see docs/adr/0014 for why this does not gate yet.'

    if ($FailOnRegression -and $ok -lt $total) { exit 1 }
    exit 0
}
finally { Pop-Location }
