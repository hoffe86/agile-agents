<#
.SYNOPSIS
    Append one structured JSON event to the current run's events.jsonl.

.DESCRIPTION
    Helper for the run-event-log skill. Validates required fields per event_type,
    stamps timestamp = current UTC ISO 8601 with millisecond precision, and
    appends one JSON line to ${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl.
    Append-only — never rewrites past events. See ../SKILL.md for full conventions.

.EXAMPLE
    .\emit-event.ps1 -RunId 01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f `
        -Agent coding -Phase coding -EventType phase_complete -Outcome success -DurationMs 184000
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RunId,
    [Parameter(Mandatory)] [ValidateSet('dev-lead','architect','coding','data-scientist','infrastructure','review-lead','code-reviewer','security-reviewer','architecture-reviewer','infrastructure-reviewer','test-reviewer')] [string] $Agent,
    [Parameter(Mandatory)] [string] $Phase,
    [Parameter(Mandatory)] [ValidateSet('run_start','run_complete','phase_start','phase_complete','tool_call','gate_check','handoff_received','error')] [string] $EventType,
    [ValidateSet('success','fail','partial')] [string] $Outcome,
    [string] $ToolName,
    [string] $ArgsSummary,
    [string] $ErrorKind,
    [string] $CorrelationId,
    [string] $ParentEventId,
    [int]    $DurationMs = -1,
    [hashtable] $Payload
)

$ErrorActionPreference = 'Stop'

function Write-StdErr([string]$msg) { [Console]::Error.WriteLine($msg) }

# Per-event_type validation
switch ($EventType) {
    'run_complete'   { if (-not $Outcome)   { Write-StdErr "emit-event: run_complete requires -Outcome";   exit 1 } }
    'phase_complete' { if (-not $Outcome)   { Write-StdErr "emit-event: phase_complete requires -Outcome"; exit 1 } }
    'gate_check'     { if (-not $Outcome)   { Write-StdErr "emit-event: gate_check requires -Outcome";     exit 1 } }
    'tool_call'      { if (-not $ToolName)  { Write-StdErr "emit-event: tool_call requires -ToolName";     exit 1 } }
    'error'          { if (-not $ErrorKind) { Write-StdErr "emit-event: error requires -ErrorKind";        exit 1 } }
}
if ($ArgsSummary -and $ArgsSummary.Length -gt 200) {
    $ArgsSummary = $ArgsSummary.Substring(0, 200)
}

# Build event with insertion-ordered keys
$evt = [ordered]@{
    timestamp  = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    run_id     = $RunId
    agent      = $Agent
    phase      = $Phase
    event_type = $EventType
}
if ($CorrelationId)            { $evt.correlation_id  = $CorrelationId }
if ($ParentEventId)            { $evt.parent_event_id = $ParentEventId }
if ($Outcome)                  { $evt.outcome         = $Outcome }
if ($DurationMs -ge 0)         { $evt.duration_ms     = $DurationMs }
if ($ToolName)                 { $evt.tool_name       = $ToolName }
if ($ArgsSummary)              { $evt.args_summary    = $ArgsSummary }
if ($ErrorKind)                { $evt.error_kind      = $ErrorKind }
if ($Payload)                  { $evt.payload         = $Payload }

$baseDir = if ($env:COPILOT_RUNS_DIR) { $env:COPILOT_RUNS_DIR } else { ".copilot-runs" }
$runDir  = Join-Path $baseDir $RunId
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Force -Path $runDir | Out-Null }
$file = Join-Path $runDir "events.jsonl"

# Compress to single line; UTF-8 without BOM; LF terminator
$json = ($evt | ConvertTo-Json -Compress -Depth 10)
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::AppendAllText($file, $json + "`n", $utf8NoBom)
exit 0