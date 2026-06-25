#Requires -Version 7.0
<#
.SYNOPSIS
    Runs the dev-lead self-benchmark harness against one of two suites.

.DESCRIPTION
    Loops the chosen suite (swe-bench-subset manifest or custom-eval task folders),
    invokes dev-lead per task, captures stdout/stderr to runs/<run-id>/<task-id>.log, and
    writes a summary.json + appends a row to baselines.md.

    NOTE: dev-lead invocation is currently a TODO (see Limitations in README.md). This
    script writes a placeholder log per task so the surrounding plumbing can be exercised
    end-to-end before the real CLI integration lands.

.PARAMETER Suite
    Which evaluation suite to run. Either 'swe-bench-subset' or 'custom-eval'.

.PARAMETER TaskFilter
    Optional regex; only tasks whose ID matches are run.

.PARAMETER PassThreshold
    Resolved-percentage threshold below which the script exits 1. Default 60.

.PARAMETER OutputRoot
    Where run artefacts land. Default: ./runs

.EXAMPLE
    ./run-eval.ps1 -Suite custom-eval

.EXAMPLE
    ./run-eval.ps1 -Suite swe-bench-subset -TaskFilter 'django'

.EXAMPLE
    ./run-eval.ps1 -Suite custom-eval -TaskFilter 'task-0[1-3]' -PassThreshold 75
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('swe-bench-subset', 'custom-eval')]
    [string]$Suite,

    [string]$TaskFilter = '.*',

    [ValidateRange(0, 100)]
    [int]$PassThreshold = 60,

    [string]$OutputRoot = (Join-Path $PSScriptRoot 'runs')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --- Resolve task list --------------------------------------------------------
$suiteRoot = Join-Path $PSScriptRoot $Suite
if (-not (Test-Path $suiteRoot)) {
    Write-Error "Suite folder not found: $suiteRoot"
    exit 2
}

$tasks = @()
switch ($Suite) {
    'swe-bench-subset' {
        $manifestPath = Join-Path $suiteRoot 'tasks.json'
        if (-not (Test-Path $manifestPath)) { Write-Error "Missing $manifestPath"; exit 2 }
        $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $tasks = $manifest | ForEach-Object {
            [pscustomobject]@{
                Id        = $_.instance_id
                PromptRef = "hf://princeton-nlp/SWE-bench_Verified#$($_.instance_id)"
                Meta      = $_
            }
        }
    }
    'custom-eval' {
        $tasksDir = Join-Path $suiteRoot 'tasks'
        if (-not (Test-Path $tasksDir)) { Write-Error "Missing $tasksDir"; exit 2 }
        $tasks = Get-ChildItem -Path $tasksDir -Directory | ForEach-Object {
            [pscustomobject]@{
                Id        = $_.Name
                PromptRef = (Join-Path $_.FullName 'prompt.md')
                Meta      = @{ folder = $_.FullName }
            }
        }
    }
}

$tasks = $tasks | Where-Object { $_.Id -match $TaskFilter }
if (-not $tasks -or $tasks.Count -eq 0) {
    Write-Error "No tasks matched filter '$TaskFilter' in suite '$Suite'."
    exit 2
}

# --- Set up run folder --------------------------------------------------------
$runId   = '{0:yyyyMMdd-HHmmss}-{1}' -f (Get-Date), $Suite
$runDir  = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

Write-Host "Run ID:    $runId"
Write-Host "Suite:     $Suite"
Write-Host "Tasks:     $($tasks.Count) (filter: '$TaskFilter')"
Write-Host "Output:    $runDir"
Write-Host ''

# --- Execute each task --------------------------------------------------------
$results = @()
foreach ($task in $tasks) {
    $logPath = Join-Path $runDir "$($task.Id).log"
    Write-Host "  → $($task.Id) ... " -NoNewline

    $status = 'failed'
    try {
        # ====================================================================
        # TODO: invoke dev-lead via copilot CLI. Expected shape (subject to
        # confirmation once the non-interactive CLI contract is finalised):
        #
        #   copilot --agent dev-lead `
        #           --prompt-file $task.PromptRef `
        #           --workspace  $runDir `
        #           --json-events `
        #     2>&1 | Tee-Object -FilePath $logPath
        #
        # Until then we write a placeholder log so the harness plumbing is
        # exercisable end-to-end and the scoring code path is testable.
        # ====================================================================

        @(
            "[$(Get-Date -Format o)] PLACEHOLDER RUN — dev-lead invocation not yet wired."
            "Suite:     $Suite"
            "Task ID:   $($task.Id)"
            "Prompt:    $($task.PromptRef)"
            ''
            'When the CLI integration lands, this file will contain the full'
            'agent transcript plus the JSON event stream from H6.'
        ) | Set-Content -Path $logPath -Encoding utf8

        # Placeholder scoring — unknown until real invocation. Mark 'failed' so
        # baselines remain honest until wired up.
        $status = 'failed'
    }
    catch {
        "[ERROR] $($_.Exception.Message)" | Add-Content -Path $logPath -Encoding utf8
        $status = 'failed'
    }

    $results += [pscustomobject]@{ id = $task.Id; status = $status }
    Write-Host $status
}

# --- Aggregate ----------------------------------------------------------------
$total    = @($results).Count
$resolved = @($results | Where-Object { $_.status -eq 'resolved' }).Count
$partial  = @($results | Where-Object { $_.status -eq 'partial'  }).Count
$failed   = @($results | Where-Object { $_.status -eq 'failed'   }).Count
$pct      = if ($total -gt 0) { [math]::Round(100.0 * $resolved / $total, 1) } else { 0 }

$summary = [ordered]@{
    suite        = $Suite
    run_id       = $runId
    total        = $total
    resolved     = $resolved
    partial      = $partial
    failed       = $failed
    resolved_pct = $pct
    partial_pct  = if ($total) { [math]::Round(100.0 * $partial / $total, 1) } else { 0 }
    failed_pct   = if ($total) { [math]::Round(100.0 * $failed  / $total, 1) } else { 0 }
    tasks        = $results
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $runDir 'summary.json') -Encoding utf8

Write-Host ''
Write-Host ('Resolved: {0}/{1} ({2}%)' -f $resolved, $total, $pct)
Write-Host ('Partial:  {0}/{1}' -f $partial, $total)
Write-Host ('Failed:   {0}/{1}' -f $failed, $total)
Write-Host ('Summary:  {0}' -f (Join-Path $runDir 'summary.json'))

# --- Exit code ----------------------------------------------------------------
if ($pct -ge $PassThreshold) {
    Write-Host "PASS (>= $PassThreshold%)"
    exit 0
} else {
    Write-Host "FAIL (< $PassThreshold%)"
    exit 1
}
