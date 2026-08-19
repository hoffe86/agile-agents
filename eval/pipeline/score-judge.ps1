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
#
# Two defects lived here. The loop below never assigned $rel/$body and never
# incremented $total, so this emitted one EMPTY "### / ```` ```` " block per file —
# 147 of them on a built .NET workspace, containing no filename and no code. The
# Windows scoring path therefore failed every criterion for reasons that had nothing
# to do with the agent. Separately (and shared with the .sh twin) build output was not
# excluded, so on a compiled project bin/obj exhausted the budget before the source
# under test was reached.
$maxPerFile = 8000
$maxTotal   = 60000
$skip = @('solution-profile.yaml')
# Generated/vendored trees: large, uninformative, reproducible from source.
$pruneDirs = 'bin|obj|node_modules|\.venv|venv|__pycache__|target|dist|packages|\.terraform|\.pytest_cache|\.mypy_cache|\.gradle|\.next|vendor'
$artifacts = ''
$omitted = New-Object System.Collections.Generic.List[string]
$total = 0
if (Test-Path $Workspace) {
    $root = (Resolve-Path $Workspace).Path
    $files = Get-ChildItem -Path $Workspace -Recurse -File |
        Where-Object {
            $_.FullName -notmatch '[\\/]\.github[\\/]' -and
            $_.FullName -notmatch '[\\/]\.git[\\/]' -and
            $_.FullName -notmatch "[\\/]($pruneDirs)[\\/]" -and
            $skip -notcontains $_.Name
        } |
        Sort-Object FullName
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($root.Length).TrimStart('\', '/').Replace('\', '/')
        $body = Get-Content -Path $f.FullName -Raw -ErrorAction SilentlyContinue
        if ([string]::IsNullOrEmpty($body)) { continue }
        # Binary files cost budget and tell the judge nothing.
        if ($body.IndexOf([char]0) -ge 0) { continue }
        if ($total -ge $maxTotal) { $omitted.Add($rel); continue }
        if ($body.Length -gt $maxPerFile) { $body = $body.Substring(0, $maxPerFile) + "`n...[truncated]" }
        $artifacts += "### $rel`n``````n$body`n``````n`n"
        $total += $body.Length
    }
}

# Tell the judge what it could NOT see, so "absent" and "not shown" stay distinguishable.
if ($omitted.Count -gt 0) {
    $artifacts += "## Files omitted (artifact budget exhausted — NOT evidence of absence)`n`n"
    $artifacts += (($omitted | Select-Object -First 40 | ForEach-Object { "- $_" }) -join "`n") + "`n"
    if ($omitted.Count -gt 40) { $artifacts += "- ...and $($omitted.Count - 40) more`n" }
    Write-Warning "[judge] artifact budget exhausted; $($omitted.Count) file(s) not shown to the judge."
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
# An UNVERIFIED criterion means the harness could not show the judge the evidence. That
# is a harness limitation, not an agent result — say so loudly rather than letting it
# settle silently into the score.
if ($resp -match '(?i)UNVERIFIED') {
    Write-Warning '[judge] at least one criterion was UNVERIFIED (evidence omitted by the artifact budget).'
    Write-Warning '[judge] This score understates the agent — treat it as a harness limit, not a result.'
}
exit (Get-VerdictExit $resp)
