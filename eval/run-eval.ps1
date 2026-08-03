#Requires -Version 7.0
<#
.SYNOPSIS
    Runs the dev-lead self-benchmark harness against one of two suites.

.DESCRIPTION
    Loops the chosen suite (swe-bench-subset manifest or custom-eval task folders),
    invokes dev-lead per task, captures stdout/stderr to runs/<run-id>/<task-id>.log, and
    writes a summary.json + appends a row to baselines.md.

    custom-eval invokes dev-lead for real via `copilot --agent agile-agents-core:dev-lead --plugin-dir
    <repo>/plugins/agile-agents-core` (the plugin folder is loaded locally so the agent resolves without installing).
    swe-bench-subset task-prep (dataset fetch + repo checkout) is not yet wired; those
    tasks fail honestly until it lands.

.PARAMETER DryRun
    Print the resolved copilot command per task without executing (no auth / no credits).

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

    [string]$OutputRoot = (Join-Path $PSScriptRoot 'runs'),

    # Print the resolved copilot command per task without executing it (no auth /
    # no credits) — use to verify the wiring.
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Repo root = parent of eval/. Loaded as a local plugin so the agent resolves
# without a prior `copilot plugin install`. --plugin-dir registers it under the
# plugin name from plugins/agile-agents-core/.github/plugin/plugin.json ("agile-agents-core"), so the supervisor
# agent is addressed as agile-agents-core:dev-lead — NOT bare dev-lead (the CLI errors
# "No such agent: dev-lead" without the plugin prefix).
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# Every plugin folder is registered, so companion skills (dotnet / python / bicep /
# terraform / trackers) resolve during a run — otherwise language tasks would silently
# fall back to repo conventions and the score wouldn't reflect the shipped suite.
$pluginDirs = @(Get-ChildItem -Path (Join-Path $repoRoot 'plugins') -Directory -Filter 'agile-agents*' |
    Sort-Object Name | ForEach-Object { $_.FullName })
$pluginDir = $pluginDirs[0]  # retained for messages that name a single representative dir
$devLeadAgent = 'agile-agents-core:dev-lead'

if (-not $DryRun -and -not (Get-Command copilot -ErrorAction SilentlyContinue)) {
    Write-Error "copilot CLI not found on PATH. Install it, run 'copilot login', or use -DryRun."
    exit 2
}

# --- dev-lead invocation ------------------------------------------------------
function Invoke-DevLead {
    param(
        [Parameter(Mandatory)][string]$PromptText,
        [Parameter(Mandatory)][string]$Workspace,
        [Parameter(Mandatory)][string]$LogPath
    )
    $copilotArgs = @(
        '-p', $PromptText
        '--agent', $devLeadAgent
    )
    foreach ($d in $pluginDirs) { $copilotArgs += @('--plugin-dir', $d) }
    $copilotArgs += @(
        '--allow-all-tools'
        '--no-ask-user'
        '--output-format', 'json'
        '-C', $Workspace
        '--add-dir', $Workspace
    )
    if ($DryRun) {
        $rendered = 'copilot ' + (($copilotArgs | ForEach-Object {
            if ($_ -match '\s') { '"{0}"' -f ($_ -replace '"', '\"') } else { $_ }
        }) -join ' ')
        @("[DRY RUN] would invoke dev-lead with:", $rendered) | Set-Content -Path $LogPath -Encoding utf8
        return 0
    }
    & copilot @copilotArgs *>&1 | Tee-Object -FilePath $LogPath | Out-Null
    return $LASTEXITCODE
}

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
                Folder    = $null
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
                Folder    = $_.FullName
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
        if ($Suite -eq 'swe-bench-subset') {
            # ponytail: SWE-bench task-prep (fetch issue text from the HF dataset +
            # checkout the repo at the base commit + extract FAIL_TO_PASS) is a separate
            # integration, not yet wired. The Invoke-DevLead helper is ready for it once
            # prep produces a prompt + workspace. Until then, fail honestly.
            @(
                "[$(Get-Date -Format o)] SWE-bench task-prep not wired."
                "Task: $($task.Id)  Ref: $($task.PromptRef)"
                "Needs: dataset fetch + repo checkout at base commit before dev-lead can run."
            ) | Set-Content -Path $logPath -Encoding utf8
            $status = 'failed'
            $results += [pscustomobject]@{ id = $task.Id; status = $status }
            Write-Host $status
            continue
        }

        $promptText = Get-Content -Path $task.PromptRef -Raw

        # Fresh per-task workspace, seeded with the task's solution-profile.yaml at the
        # documented locations so dev-lead reads its operational profile.
        $ws = Join-Path $runDir "ws/$($task.Id)"
        New-Item -ItemType Directory -Force -Path (Join-Path $ws '.github') | Out-Null
        $profileSrc = Join-Path $task.Folder 'solution-profile.yaml'
        if (Test-Path $profileSrc) {
            Copy-Item $profileSrc (Join-Path $ws 'solution-profile.yaml') -Force
            Copy-Item $profileSrc (Join-Path $ws '.github/solution-profile.yaml') -Force
        }

        $exit = Invoke-DevLead -PromptText $promptText -Workspace $ws -LogPath $logPath

        if ($DryRun) {
            $status = 'failed'   # not a real run; excluded from a real score
        }
        elseif ($exit -ne 0 -or -not (Test-Path $logPath) -or (Get-Item $logPath).Length -eq 0) {
            $status = 'failed'
        }
        else {
            # Scoring (exit 0 = resolved, 2 = partial, else failed):
            #   per-task score.ps1 / score.sh = deterministic override (build/test);
            #   otherwise the default LLM judge grades the workspace vs acceptance.md.
            $scorePs = Join-Path $task.Folder 'score.ps1'
            $scoreSh = Join-Path $task.Folder 'score.sh'
            $acceptance = Join-Path $task.Folder 'acceptance.md'
            if (Test-Path $scorePs) {
                & pwsh -NoProfile -File $scorePs -Workspace $ws *>> $logPath
                $status = switch ($LASTEXITCODE) { 0 { 'resolved' } 2 { 'partial' } default { 'failed' } }
            }
            elseif (Test-Path $scoreSh) {
                & bash $scoreSh "$ws" *>> $logPath
                $status = switch ($LASTEXITCODE) { 0 { 'resolved' } 2 { 'partial' } default { 'failed' } }
            }
            else {
                & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'score-judge.ps1') -Workspace $ws -AcceptancePath $acceptance *>> $logPath
                $status = switch ($LASTEXITCODE) { 0 { 'resolved' } 2 { 'partial' } default { 'failed' } }
            }
        }
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
