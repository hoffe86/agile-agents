#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Sum cost_usd / tokens from a run-event-log JSONL file.

.DESCRIPTION
  Reads .copilot-runs/<run-id>/events.jsonl, aggregates cost_usd, tokens_in,
  tokens_out per `agent` and per `phase`, and writes a JSON summary to stdout.
  Exits non-zero if -Threshold is supplied and total_usd exceeds it.

.PARAMETER EventLog
  Path to events.jsonl.

.PARAMETER Threshold
  Optional USD limit. Exit code 2 if total_usd > Threshold.

.EXAMPLE
  ./sum-costs.ps1 -EventLog .copilot-runs/2026-04-12/events.jsonl -Threshold 25
#>
param(
    [Parameter(Mandatory = $true)] [string] $EventLog,
    [double] $Threshold
)

if (-not (Test-Path $EventLog)) {
    Write-Error "Event log not found: $EventLog"
    exit 1
}

$total = 0.0
$byAgent = @{}
$byPhase = @{}

Get-Content -LiteralPath $EventLog | ForEach-Object {
    if (-not $_.Trim()) { return }
    try { $e = $_ | ConvertFrom-Json } catch { return }
    if ($null -eq $e.cost_usd) { return }

    $cost = [double] $e.cost_usd
    $tin  = [int]    ($e.tokens_in  ?? 0)
    $tout = [int]    ($e.tokens_out ?? 0)
    $total += $cost

    foreach ($pair in @(@{ Map = $byAgent; Key = $e.agent }, @{ Map = $byPhase; Key = $e.phase })) {
        $key = $pair.Key; if (-not $key) { $key = 'unknown' }
        if (-not $pair.Map.ContainsKey($key)) {
            $pair.Map[$key] = [pscustomobject]@{ cost_usd = 0.0; tokens_in = 0; tokens_out = 0 }
        }
        $pair.Map[$key].cost_usd  += $cost
        $pair.Map[$key].tokens_in += $tin
        $pair.Map[$key].tokens_out += $tout
    }
}

[pscustomobject]@{
    total_usd = [math]::Round($total, 4)
    by_agent  = $byAgent
    by_phase  = $byPhase
} | ConvertTo-Json -Depth 5

if ($PSBoundParameters.ContainsKey('Threshold') -and $total -gt $Threshold) {
    Write-Error "Cost $total USD exceeds threshold $Threshold USD"
    exit 2
}
