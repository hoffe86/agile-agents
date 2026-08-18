#Requires -Version 7.0
<#
.SYNOPSIS
    Default eval scorer — grades a produced workspace against a task's acceptance.md
    using Copilot as an impartial judge (LLM-as-judge).

.DESCRIPTION
    Collects the artifacts the agent produced in the workspace (excluding the seeded
    solution-profile.yaml), fills the shared judge prompt with the acceptance criteria
    and those artifacts, asks `copilot` for a verdict, and maps it to an exit code:

        0 = resolved, 2 = partial, 1 = failed (or any error / unparseable verdict)

    This is the same exit-code contract as a per-task score.ps1, so run-eval.ps1 calls
    whichever exists (per-task override wins) the same way. Use a deterministic per-task
    score.ps1 instead when acceptance needs a real build/test rather than a judgement.

.PARAMETER Workspace
    The per-task workspace dev-lead ran in (its produced files are graded).

.PARAMETER AcceptancePath
    Path to the task's acceptance.md.

.PARAMETER PromptTemplate
    Judge prompt template. Default: references/judge-prompt.md next to this script.

.PARAMETER SelfTest
    Run the verdict-parser self-check (no copilot call) and exit 0 if it passes.
#>
[CmdletBinding()]
param(
    [string]$Workspace,
    [string]$AcceptancePath,
    [string]$PromptTemplate = (Join-Path $PSScriptRoot 'references/judge-prompt.md'),
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Map a judge response to the score exit code. Last VERDICT line wins; anything
# unparseable is treated as failed so an unclear judge never inflates the score.
function Get-VerdictExit {
    param([string]$Text)
    $m = [regex]::Matches($Text, '(?im)^\s*VERDICT:\s*(RESOLVED|PARTIAL|FAILED)\s*$')
    if ($m.Count -eq 0) { return 1 }
    switch ($m[$m.Count - 1].Groups[1].Value.ToUpperInvariant()) {
        'RESOLVED' { 0 } 'PARTIAL' { 2 } default { 1 }
    }
}

if ($SelfTest) {
    $cases = @(
        @{ t = "1. PASS - ok`nVERDICT: RESOLVED"; e = 0 }
        @{ t = "VERDICT: PARTIAL`n"; e = 2 }
        @{ t = "VERDICT: FAILED"; e = 1 }
        @{ t = "no verdict here"; e = 1 }
        @{ t = "VERDICT: RESOLVED`nVERDICT: FAILED"; e = 1 }   # last wins
        @{ t = "verdict: resolved"; e = 0 }                    # case-insensitive
    )
    $ok = $true
    foreach ($c in $cases) {
        $got = Get-VerdictExit $c.t
        if ($got -ne $c.e) { Write-Host "FAIL: '$($c.t -replace "`n",'\n')' => $got (want $($c.e))"; $ok = $false }
    }
    if ($ok) { Write-Host 'score-judge self-test: PASS'; exit 0 } else { exit 1 }
}

if (-not $Workspace -or -not $AcceptancePath) {
    Write-Error 'Workspace and AcceptancePath are required (or use -SelfTest).'; exit 1
}
if (-not (Get-Command copilot -ErrorAction SilentlyContinue)) {
    Write-Host '[judge] copilot not on PATH — cannot score.'; exit 1
}
if (-not (Test-Path $AcceptancePath)) { Write-Host "[judge] missing acceptance: $AcceptancePath"; exit 1 }

# --- Collect produced artifacts (exclude the seeded profile + .github) -----------
$maxPerFile = 8000
$maxTotal   = 60000
$skip = @('solution-profile.yaml')
$artifacts = ''
$total = 0
if (Test-Path $Workspace) {
    $files = Get-ChildItem -Path $Workspace -Recurse -File |
        Where-Object { $_.FullName -notmatch '[\\/]\.github[\\/]' -and $skip -notcontains $_.Name } |
        Sort-Object FullName
    foreach ($f in $files) {
        if ($total -ge $maxTotal) { break }
        $artifacts += "### $rel`n```````n$body`n```````n`n"
    }
}
if ([string]::IsNullOrWhiteSpace($artifacts)) {
    Write-Host '[judge] agent produced no gradable files → failed.'; exit 1
}

$prompt = (Get-Content -Path $PromptTemplate -Raw).
    Replace('{{ACCEPTANCE}}', (Get-Content -Path $AcceptancePath -Raw)).
    Replace('{{ARTIFACTS}}', $artifacts)

# Read-only judgement: artifacts are inlined, so no tools are needed.
$resp = & copilot -p $prompt -s --no-ask-user --allow-all-tools -C $Workspace 2>&1 | Out-String
Write-Host '[judge] ----- response -----'
Write-Host $resp.Trim()
Write-Host '[judge] ----------------------'
exit (Get-VerdictExit $resp)
