#Requires -Version 7.0
<#
.SYNOPSIS
    Runs the dev-lead self-benchmark harness against one of two suites.

.DESCRIPTION
    Loops the chosen suite (swe-bench-subset manifest or custom-eval task folders),
    invokes dev-lead per task, captures stdout/stderr to runs/<run-id>/<task-id>.log, and
    writes summary.json. Measured baselines are recorded manually in baselines.md.

    Non-dry runs currently fail closed before staging or invoking a model because no OS
    sandbox enforces credential-free, network-disabled access. DryRun performs offline
    fixture preflight/staging. The mandatory human plan-approval gate remains unchanged.
    swe-bench-subset task-prep (dataset fetch + repo checkout) is not yet wired; those
    tasks report setup_error honestly until it lands.

.PARAMETER DryRun
    Preflight profiles and paths and stage declared inputs without invoking any model.

.PARAMETER Suite
    Which evaluation suite to run. Either 'swe-bench-subset' or 'custom-eval'.

.PARAMETER TaskFilter
    Optional regex; only tasks whose ID matches are run.

.PARAMETER PassThreshold
    Resolved-percentage threshold below which the script exits 1. Default 60.

.PARAMETER OutputRoot
    Where run artefacts land. Default: ./runs

.EXAMPLE
    ./run-eval.ps1 -Suite custom-eval -DryRun

.EXAMPLE
    ./run-eval.ps1 -Suite swe-bench-subset -DryRun -TaskFilter 'django'

.EXAMPLE
    ./run-eval.ps1 -Suite custom-eval -DryRun -TaskFilter 'task-0[1-3]' -PassThreshold 75
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

    # Preflight/stage fixtures and print the resolved command without executing it
    # (no auth / no credits) — use to verify the wiring.
    [switch]$DryRun,

    # Run against the developer's own Copilot configuration instead of an isolated one.
    # This reinstates the plugin-shadowing defect described below, so the run no longer
    # measures the working tree. Only useful for comparing against historical numbers.
    [switch]$NoIsolation,

    # The model the agent runs on. Pinned rather than inherited: the CLI default comes
    # from user config, which an isolated run does not have — so leaving it unset silently
    # changed the model under test from claude-opus-4.8 to claude-sonnet-5 and made
    # isolated and non-isolated runs incomparable for reasons unrelated to isolation.
    [string]$AgentModel = $(if ($env:AGENT_MODEL) { $env:AGENT_MODEL } else { 'claude-opus-4.8' }),

    # The model the judge runs on. Must differ from the agent's: a model grading its own
    # output is not an independent measurement.
    [string]$JudgeModel = $(if ($env:JUDGE_MODEL) { $env:JUDGE_MODEL } else { 'gpt-5.6-sol' }),

    # Which default judge grades a task that has no deterministic score.ps1/score.sh.
    #   deepeval — runs in the workspace with tools and loads the `acceptance-grading`
    #              skill, so it verifies rather than infers. Default since the 2026-08-19
    #              A/B (see eval/baselines.md): the two judges agreed on only 3 of 10
    #              tasks, and on 6 of the 7 disagreements the shell judge was
    #              demonstrably wrong — all 4 of its `failed` verdicts were its own
    #              artifact-collection defects rather than agent failures.
    #   shell    — score-judge.{ps1,sh}: uses a capped artifact dump for orientation,
    #              with native verification and the same structured outcome contract.
    #   both     — run each and record whether they agree.
    # Default judges: 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup_error.
    [ValidateSet('shell', 'deepeval', 'both')]
    [string]$Scorer = $(if ($env:EVAL_SCORER) { $env:EVAL_SCORER } else { 'deepeval' })
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-FatalError {
    <#
        Writes a setup error and exits with a deterministic code.

        `$ErrorActionPreference = 'Stop'` makes `Write-Error` terminating, so the
        `exit 2` that used to follow it never ran and the script exited 1 instead —
        while the .sh twin exited 2 for the same condition. Callers (and CI) cannot
        distinguish "bad setup" from "tasks failed" when the code is wrong.
    #>
    param(
        [Parameter(Mandatory)][string]$Message,
        [int]$Code = 2
    )
    [Console]::Error.WriteLine($Message)
    exit $Code
}

# Repo root = parent of eval/. Loaded as a local plugin so the agent resolves
# without a prior `copilot plugin install`. --plugin-dir registers it under the
# plugin name from plugins/agile-agents-core/.github/plugin/plugin.json ("agile-agents-core"), so the supervisor
# agent is addressed as agile-agents-core:dev-lead — NOT bare dev-lead (the CLI errors
# "No such agent: dev-lead" without the plugin prefix).
# Repo root = two levels up from eval/pipeline/. Loaded as a local plugin so the agent
# resolves without a prior `copilot plugin install`. --plugin-dir registers it under the
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
# Every plugin folder is registered, so companion skills (dotnet / python / bicep /
# terraform / trackers) resolve during a run — otherwise language tasks would silently
# fall back to repo conventions and the score wouldn't reflect the shipped suite.
$pluginDirs = @(Get-ChildItem -Path (Join-Path $repoRoot 'plugins') -Directory -Filter 'agile-agents*' |
    Sort-Object Name | ForEach-Object { $_.FullName })
$pluginDir = $pluginDirs[0]  # retained for messages that name a single representative dir
$devLeadAgent = 'agile-agents-core:dev-lead'

if (-not $DryRun) {
    Write-FatalError 'Live evaluation is disabled until an OS sandbox enforces credential-free, network-disabled access for both agent and judge processes. Use -DryRun for offline staging and preflight.'
}

if (-not $DryRun -and $Suite -ne 'custom-eval' -and -not (Get-Command copilot -ErrorAction SilentlyContinue)) {
    Write-FatalError "copilot CLI not found on PATH. Install it, run 'copilot login', or use -DryRun."
}

# A model grading its own output is not an independent measurement. Refuse rather than
# quietly produce a self-assessed score.
if ($AgentModel -eq $JudgeModel) {
    Write-FatalError "Agent and judge models are both '$AgentModel'. A model grading its own output is not an independent measurement — set -JudgeModel to a different model."
}

# --- Isolated Copilot configuration root --------------------------------------
# Plugins install at **User** scope under the home directory, and `--plugin-dir` does
# NOT override an installed plugin of the same name — the installed copy wins silently.
# A run that believed it was exercising the working tree was reading whatever version
# happened to be installed (found at v0.14.0 against a working tree at v0.16.0). Every
# measurement of a modified existing skill was therefore of the wrong file.
#
# Redirecting HOME / USERPROFILE to a throwaway directory removes User-scope plugins from
# resolution, leaving --plugin-dir as the only source.
#
# Two consequences, both deliberate and both reported in the banner and summary.json:
#   1. Stored auth does not survive isolation, so a token must be supplied via the
#      environment. That is how CI supplies it anyway.
#   2. The developer's own MCP servers are configured in the same place, so they are
#      dropped. Servers declared by the plugins themselves (plugins/agile-agents-core/.mcp.json
#      ships context7, microsoft-docs and playwright) still load, because they arrive via
#      --plugin-dir. That is the desired line: the harness keeps the tools it declares and
#      loses the ones that merely happened to be on the developer's machine. Verified —
#      task-04 depends on microsoft-docs for its primary-sources criterion and still scores
#      `resolved` under isolation.
$isolate = -not $NoIsolation
$isolatedHome = $null

if ($isolate -and -not $DryRun -and $Suite -ne 'custom-eval') {
    $tokenNames = @('COPILOT_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')
    $haveToken = $false
    foreach ($n in $tokenNames) {
        if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($n))) { $haveToken = $true; break }
    }
    if (-not $haveToken) {
        # Fail rather than fall back. A silent fall-back to the developer's config would
        # produce a plausible-looking score for the wrong plugin version — exactly the
        # class of defect this isolation exists to remove.
        Write-FatalError @"
Isolated runs need a token in the environment, because stored auth does not survive
isolation. Set one of: $($tokenNames -join ', ').

  PowerShell:  `$env:GH_TOKEN = (gh auth token)

Or re-run with -NoIsolation to use your own Copilot configuration — but be aware that
an installed plugin of the same name shadows --plugin-dir, so the run will NOT measure
the working tree.
"@
    }
}

function Get-ScoreStatus {
    param([int]$Code, [string]$ResultPath, [string]$Acceptance)
    if ($ResultPath) {
        $value = & python (Join-Path $repoRoot 'eval/grading.py') --result-status $ResultPath --exit-code $Code --acceptance $Acceptance
        if ($LASTEXITCODE -ne 0 -or $value -notin @('resolved', 'partial', 'failed', 'unverified', 'setup_error')) {
            return 'setup_error'
        }
        return $value
    }
    # Deterministic task scorers retain their legacy codes, plus explicit uncertainty.
    switch ($Code) {
        0 { 'resolved' } 1 { 'failed' } 2 { 'partial' } 3 { 'unverified' } default { 'setup_error' }
    }
}

function Invoke-WithIsolation {
    <#
        Runs a scriptblock with the isolated configuration root in effect, restoring the
        caller's environment afterwards so nothing leaks into the rest of the script.
        Child processes (the judge runs as its own pwsh) inherit these, so they are
        isolated too — the judge loads plugins exactly like the agent did.
    #>
    param([Parameter(Mandatory)][scriptblock]$Body)

    $savedProfile = $env:USERPROFILE
    $savedHome    = $env:HOME
    try {
        if ($isolatedHome) {
            $env:USERPROFILE = $isolatedHome
            $env:HOME        = $isolatedHome
        }
        & $Body
    }
    finally {
        $env:USERPROFILE = $savedProfile
        $env:HOME        = $savedHome
    }
}

function Invoke-Copilot {
    param(
        [Parameter(Mandatory)][string[]]$CopilotArgs,
        [Parameter(Mandatory)][string]$LogPath
    )
    Invoke-WithIsolation {
        & copilot @CopilotArgs *>&1 | Tee-Object -FilePath $LogPath | Out-Null
    }
    return $LASTEXITCODE
}

# --- dev-lead invocation ------------------------------------------------------
function Invoke-DevLead {
    param(
        [Parameter(Mandatory)][string]$PromptText,
        [Parameter(Mandatory)][string]$Workspace,
        [Parameter(Mandatory)][string]$BaselineDirectory,
        [Parameter(Mandatory)][string]$LogPath
    )
    $copilotArgs = @(
        '-p', $PromptText
        '--agent', $devLeadAgent
        '--model', $AgentModel
    )
    foreach ($d in $pluginDirs) { $copilotArgs += @('--plugin-dir', $d) }
    $copilotArgs += @(
        '--allow-all-tools'
        '--no-ask-user'
        '--output-format', 'json'
        '-C', $Workspace
        '--add-dir', $Workspace
        '--add-dir', $BaselineDirectory
    )
    if ($DryRun) {
        $rendered = 'copilot ' + (($copilotArgs | ForEach-Object {
            if ($_ -match '\s') { '"{0}"' -f ($_ -replace '"', '\"') } else { $_ }
        }) -join ' ')
        @("[DRY RUN] would invoke dev-lead with:", $rendered) | Set-Content -Path $LogPath -Encoding utf8
        return 0
    }
    return (Invoke-Copilot -CopilotArgs $copilotArgs -LogPath $LogPath)
}

# --- Resolve task list --------------------------------------------------------
$suiteRoot = Join-Path $PSScriptRoot $Suite
if (-not (Test-Path $suiteRoot)) {
    Write-FatalError "Suite folder not found: $suiteRoot"
}

$tasks = @()
switch ($Suite) {
    'swe-bench-subset' {
        $manifestPath = Join-Path $suiteRoot 'tasks.json'
        if (-not (Test-Path $manifestPath)) { Write-FatalError "Missing $manifestPath" }
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
        if (-not (Test-Path $tasksDir)) { Write-FatalError "Missing $tasksDir" }
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
    Write-FatalError "No tasks matched filter '$TaskFilter' in suite '$Suite'."
}

# --- Set up run folder --------------------------------------------------------
$runId   = '{0:yyyyMMdd-HHmmss}-{1}' -f (Get-Date), $Suite
$runDir  = Join-Path $OutputRoot $runId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

if ($isolate -and -not $DryRun) {
    $isolatedHome = Join-Path $runDir '.copilot-home'
    New-Item -ItemType Directory -Force -Path $isolatedHome | Out-Null
}

Write-Host "Run ID:    $runId"
Write-Host "Suite:     $Suite"
Write-Host "Models:    agent=$AgentModel  judge=$JudgeModel"
Write-Host "Scorer:    $Scorer$(if ($Scorer -eq 'both') { ' (shell authoritative; agreement recorded)' })"
Write-Host "Tasks:     $($tasks.Count) (filter: '$TaskFilter')"
Write-Host "Output:    $runDir"
if ($DryRun) {
    Write-Host "Config:    (dry run — the CLI is not invoked)"
} elseif ($Suite -eq 'custom-eval') {
    Write-Host "Config:    noninteractive live evaluation is blocked by the mandatory human plan-approval gate"
} elseif ($isolate) {
    Write-Host "Config:    isolated ($isolatedHome) — plugins and MCP servers come only from --plugin-dir"
} else {
    Write-Host "Config:    NOT ISOLATED — user plugins shadow --plugin-dir; this does not measure the working tree" -ForegroundColor Yellow
}
Write-Host ''

# Stage every selected custom-eval task before any agent invocation. The shared helper
# validates profiles and declared paths first, and exposes the immutable baseline path.
$preparedTasks = @{}
if ($Suite -eq 'custom-eval') {
    $prepareScript = Join-Path $suiteRoot 'prepare_inputs.py'
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        $missingPythonSummary = [ordered]@{
            suite = $Suite; run_id = $runId; run_status = 'setup_error'
            total = $tasks.Count; setup_error_count = $tasks.Count
            resolved = 0; partial = 0; failed = 0; unverified = 0
            skipped = 0; blocked_approval_count = 0; dry_run = [bool]$DryRun
            tasks = @($tasks | ForEach-Object { [ordered]@{ id = $_.Id; status = 'setup_error' } })
            setup_errors = @('python is required to preflight and stage custom-eval fixtures')
        }
        $missingPythonSummary | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $runDir 'summary.json') -Encoding utf8
        Write-FatalError "python is required to preflight and stage custom-eval fixtures."
    }
    $prepareArgs = @($prepareScript, '--suite-root', $suiteRoot, '--run-dir', $runDir)
    foreach ($task in $tasks) { $prepareArgs += @('--task-id', $task.Id) }
    $prepareOutput = (& python @prepareArgs 2>&1 | Out-String).Trim()
    $prepareExit = $LASTEXITCODE
    try {
        $prepareResult = $prepareOutput | ConvertFrom-Json -AsHashtable
        if ($prepareResult -isnot [System.Collections.IDictionary] -or
            -not $prepareResult.ContainsKey('status') -or
            -not $prepareResult.ContainsKey('tasks') -or
            $prepareResult.tasks -isnot [array] -or
            @($prepareResult.tasks).Count -ne @($tasks).Count) {
            throw 'invalid preparation result schema'
        }
        foreach ($row in $prepareResult.tasks) {
            if ($row -isnot [System.Collections.IDictionary] -or
                -not $row.ContainsKey('task_id') -or -not $row.ContainsKey('status')) {
                throw 'invalid preparation task row'
            }
        }
        if (@($prepareResult.tasks.task_id | Select-Object -Unique).Count -ne @($tasks).Count -or
            @(Compare-Object @($tasks.Id) @($prepareResult.tasks.task_id)).Count) {
            throw 'preparation task ids differ from selected tasks'
        }
    } catch {
        $prepareResult = @{
            status = 'setup_error'
            tasks = @($tasks | ForEach-Object { @{task_id = $_.Id; status = 'setup_error'} })
            errors = @("preparation returned invalid JSON/schema (exit $prepareExit): $prepareOutput")
        }
    }

    $prepareResult | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $runDir 'preflight.json') -Encoding utf8
    if ($prepareExit -ne 0 -or $prepareResult.status -ne 'prepared') {
        $setupErrors = @($prepareResult.errors)
        $taskStatuses = @{}
        foreach ($row in $prepareResult.tasks) { $taskStatuses[$row.task_id] = $row.status }
        foreach ($task in $tasks) {
            $status = if ($taskStatuses.ContainsKey($task.Id)) { $taskStatuses[$task.Id] } else { 'setup_error' }
            $log = @("[setup_error] fixture preparation did not complete."; ($setupErrors | ConvertTo-Json -Depth 6))
            $log | Set-Content -Path (Join-Path $runDir "$($task.Id).log") -Encoding utf8
        }
        $setupSummary = [ordered]@{
            suite = $Suite
            run_id = $runId
            run_status = 'setup_error'
            total = $tasks.Count
            setup_error_count = $tasks.Count
            resolved = 0
            partial = 0
            failed = 0
            unverified = 0
            blocked_approval_count = 0
            skipped = 0
            dry_run = [bool]$DryRun
            tasks = @($tasks | ForEach-Object {
                [ordered]@{ id = $_.Id; status = 'setup_error'; preparation_status = $taskStatuses[$_.Id] }
            })
            setup_errors = $setupErrors
        }
        $setupSummary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $runDir 'summary.json') -Encoding utf8
        Write-Host "SETUP ERROR — no agent or judge was invoked. See $(Join-Path $runDir 'preflight.json')."
        exit 2
    }
    foreach ($row in $prepareResult.tasks) { $preparedTasks[$row.task_id] = $row }
    Write-Host "Fixture preflight: passed; staged immutable baseline inputs outside each workspace."
}

# The current CLI runner is unattended (`--no-ask-user`) but the RPI pipeline's plan
# approval is mandatory. Never let an unattended run turn that human gate into approval.
if ($Suite -eq 'custom-eval' -and -not $DryRun) {
    $blockedTasks = @($tasks | ForEach-Object {
        [ordered]@{ id = $_.Id; status = 'blocked_approval' }
    })
    $blockedSummary = [ordered]@{
        suite = $Suite
        run_id = $runId
        run_status = 'blocked_approval'
        blocking_gate = 'human_plan_approval'
        reason = 'The noninteractive runner cannot receive the mandatory plan approval.'
        total = $tasks.Count
        blocked_approval_count = $tasks.Count
        setup_error_count = 0
        resolved = 0
        partial = 0
        failed = 0
        unverified = 0
        skipped = 0
        dry_run = $false
        tasks = $blockedTasks
    }
    $blockedSummary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $runDir 'summary.json') -Encoding utf8
    Write-Host "BLOCKED — custom-eval requires human plan approval; no agent or judge was invoked."
    Write-Host ('Summary:  {0}' -f (Join-Path $runDir 'summary.json'))
    exit 3
}

# --- Execute each task --------------------------------------------------------
$results = @()
$scorerComparison = @()
foreach ($task in $tasks) {
    $logPath = Join-Path $runDir "$($task.Id).log"
    Write-Host "  → $($task.Id) ... " -NoNewline

    $status = 'setup_error'
    $grading = $null
    try {
        if ($Suite -eq 'swe-bench-subset') {
            # ponytail: SWE-bench task-prep (fetch issue text from the HF dataset +
            # checkout the repo at the base commit + extract FAIL_TO_PASS) is a separate
            # integration, not yet wired. The Invoke-DevLead helper is ready for it once
            # prep produces a prompt + workspace. Until then, report a setup error.
            @(
                "[$(Get-Date -Format o)] SWE-bench task-prep not wired."
                "Task: $($task.Id)  Ref: $($task.PromptRef)"
                "Needs: dataset fetch + repo checkout at base commit before dev-lead can run."
            ) | Set-Content -Path $logPath -Encoding utf8
            $status = 'setup_error'
            $results += [pscustomobject]@{ id = $task.Id; status = $status; reason = 'SWE-bench task-prep not wired' }
            Write-Host $status
            continue
        }

        $promptText = Get-Content -Path $task.PromptRef -Raw

        $ws = if ($Suite -eq 'custom-eval') {
            $preparedTasks[$task.Id].workspace
        } else {
            Join-Path $runDir "ws/$($task.Id)"
        }
        $baselineDirectory = if ($Suite -eq 'custom-eval') {
            $preparedTasks[$task.Id].baseline_dir
        } else {
            $ws
        }

        $exit = Invoke-DevLead -PromptText $promptText -Workspace $ws -BaselineDirectory $baselineDirectory -LogPath $logPath

        if ($DryRun) {
            # A dry run never invoked the agent, so there is nothing to grade. Marking
            # these 'failed' (as this did) is a lie in the honest-looking direction: the
            # log reads "Failed: N/N" while the job exits 0 because the threshold was
            # set low, so a wiring check and a total collapse look identical.
            $status = 'skipped'
        }
        elseif ($exit -ne 0 -or -not (Test-Path $logPath) -or (Get-Item $logPath).Length -eq 0) {
            $status = 'setup_error'
        }
        else {
            # Scoring: 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup_error.
            #   per-task score.ps1 / score.sh = deterministic override (build/test);
            #   otherwise the default LLM judge grades the workspace vs acceptance.md.
            $scorePs = Join-Path $task.Folder 'score.ps1'
            $scoreSh = Join-Path $task.Folder 'score.sh'
            $acceptance = Join-Path $task.Folder 'acceptance.md'
            if (Test-Path $scorePs) {
                & pwsh -NoProfile -File $scorePs -Workspace $ws *>> $logPath
                $status = Get-ScoreStatus -Code $LASTEXITCODE
            }
            elseif (Test-Path $scoreSh) {
                & bash $scoreSh "$ws" *>> $logPath
                $status = Get-ScoreStatus -Code $LASTEXITCODE
            }
            else {
                # Both judges invoke the CLI, so both run under the same isolation — a
                # judge loading a different plugin set than the agent would grade against
                # conventions the agent never saw.
                $shellStatus = $null
                $deepStatus  = $null
                $shellResult = Join-Path $runDir "$($task.Id).shell.json"
                $deepResult = Join-Path $runDir "$($task.Id).deepeval.json"

                if ($Scorer -in @('shell', 'both')) {
                    Invoke-WithIsolation {
                        & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'score-judge.ps1') -Workspace $ws -AcceptancePath $acceptance -JudgeModel $JudgeModel -BaselineDirectory $baselineDirectory -ResultJson $shellResult *>> $logPath
                    }
                    $shellStatus = Get-ScoreStatus -Code $LASTEXITCODE -ResultPath $shellResult -Acceptance $acceptance
                }

                if ($Scorer -in @('deepeval', 'both')) {
                    $scoreWorkspace = Join-Path $repoRoot 'eval/deepeval/score_workspace.py'
                    $deepArgs = @($scoreWorkspace, $ws, $acceptance, '--model', $JudgeModel,
                                  '--baseline-dir', $baselineDirectory, '--result-json', $deepResult)
                    if ($isolatedHome) { $deepArgs += @('--isolated-home', $isolatedHome) }
                    # No Invoke-WithIsolation here: the scorer takes the isolated home as an
                    # argument and sets it on the child itself, so the redirect cannot leak.
                    & python @deepArgs *>> $logPath
                    $deepStatus = Get-ScoreStatus -Code $LASTEXITCODE -ResultPath $deepResult -Acceptance $acceptance
                }

                if ($Scorer -eq 'both') {
                    $agree = $shellStatus -eq $deepStatus
                    $line = "[scorer] shell=$shellStatus deepeval=$deepStatus agree=$agree"
                    $line | Add-Content -Path $logPath -Encoding utf8
                    Write-Host "     $line"
                    $scorerComparison += [ordered]@{
                        task = $task.Id; shell = $shellStatus; deepeval = $deepStatus; agree = $agree
                        shell_result = $shellResult; deepeval_result = $deepResult
                    }
                    # The shell judge stays authoritative while comparing, so a disagreement
                    # cannot silently move the headline score during the evaluation itself.
                    $status = $shellStatus
                }
                else {
                    $status = if ($Scorer -eq 'deepeval') { $deepStatus } else { $shellStatus }
                }
                $grading = [ordered]@{
                    shell = if (Test-Path $shellResult) { Get-Content $shellResult -Raw | ConvertFrom-Json } else { $null }
                    deepeval = if (Test-Path $deepResult) { Get-Content $deepResult -Raw | ConvertFrom-Json } else { $null }
                }
            }
        }
    }
    catch {
        "[ERROR] $($_.Exception.Message)" | Add-Content -Path $logPath -Encoding utf8
        $status = 'setup_error'
    }

    $results += [pscustomobject]@{ id = $task.Id; status = $status; grading = $grading }
    Write-Host $status
}

# --- Aggregate ----------------------------------------------------------------
$total    = @($results).Count
$resolved = @($results | Where-Object { $_.status -eq 'resolved' }).Count
$partial  = @($results | Where-Object { $_.status -eq 'partial'  }).Count
$failed   = @($results | Where-Object { $_.status -eq 'failed'   }).Count
$skipped  = @($results | Where-Object { $_.status -eq 'skipped'  }).Count
$unverified = @($results | Where-Object status -eq 'unverified').Count
$setupErrors = @($results | Where-Object status -eq 'setup_error').Count
$pct      = if ($total -gt 0) { [math]::Round(100.0 * $resolved / $total, 1) } else { 0 }

$summary = [ordered]@{
    suite        = $Suite
    run_id       = $runId
    run_status   = if ($DryRun) { 'skipped' } elseif ($setupErrors) { 'setup_error' } elseif ($unverified) { 'unverified' } else { 'scored' }
    total        = $total
    resolved     = $resolved
    partial      = $partial
    failed       = $failed
    skipped      = $skipped
    unverified   = $unverified
    setup_error_count = $setupErrors
    blocked_approval_count = 0
    dry_run      = [bool]$DryRun
    scorer       = $Scorer
    live_run_status = if ($Suite -eq 'custom-eval' -and $DryRun) {
        'blocked_approval: live runs also require the unavailable OS sandbox'
    } else { $null }
    # Pinned, and recorded: a score is only comparable to another score from the same pair.
    agent_model  = $AgentModel
    judge_model  = $JudgeModel
    # Whether the run measured the working tree or the developer's installed plugins.
    # A score carries a different meaning in each case, so it travels with the score.
    isolated     = [bool]$isolate
    mcp_servers  = if ($isolate) { 'plugin-declared only' } else { 'plugin-declared + user config' }
    resolved_pct = $pct
    partial_pct  = if ($total) { [math]::Round(100.0 * $partial / $total, 1) } else { 0 }
    failed_pct   = if ($total) { [math]::Round(100.0 * $failed  / $total, 1) } else { 0 }
    # Populated only by -Scorer both. This is the evidence the cutover decision rests on:
    # a per-task record of where the two judges agreed, kept even when they did not.
    scorer_comparison = $scorerComparison
    scorer_agreement_pct = if ($scorerComparison.Count) {
        [math]::Round(100.0 * (@($scorerComparison | Where-Object { $_.agree }).Count) / $scorerComparison.Count, 1)
    } else { $null }
    tasks        = $results
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $runDir 'summary.json') -Encoding utf8

if ($scorerComparison.Count) {
    $agreed = @($scorerComparison | Where-Object { $_.agree }).Count
    Write-Host ''
    Write-Host ("Scorer agreement: {0}/{1} ({2}%)" -f $agreed, $scorerComparison.Count, $summary.scorer_agreement_pct)
    foreach ($d in $scorerComparison | Where-Object { -not $_.agree }) {
        # Named individually: an aggregate agreement rate hides which task disagreed, and
        # that task is the whole reason to look.
        Write-Host ("  DISAGREE  {0}: shell={1} deepeval={2}" -f $d.task, $d.shell, $d.deepeval)
    }
}

Write-Host ''
if ($DryRun) {
    # Wiring check only — say so plainly rather than reporting a score nobody computed.
    Write-Host ("DRY RUN — wiring validated for {0} task(s); none executed, none scored." -f $total)
    if ($Suite -eq 'custom-eval') {
        Write-Host 'Live run blocked: OS sandbox unavailable; mandatory plan approval also requires a human response.'
    }
    Write-Host ('Summary:  {0}' -f (Join-Path $runDir 'summary.json'))
    Write-Host 'Live scoring remains disabled until OS sandbox isolation and human plan approval are available.'
    exit 0
}

Write-Host ('Resolved: {0}/{1} ({2}%)' -f $resolved, $total, $pct)
Write-Host ('Partial:  {0}/{1}' -f $partial, $total)
Write-Host ('Failed:   {0}/{1}' -f $failed, $total)
Write-Host ('Unverified: {0}/{1}' -f $unverified, $total)
Write-Host ('Setup error: {0}/{1}' -f $setupErrors, $total)
Write-Host ('Summary:  {0}' -f (Join-Path $runDir 'summary.json'))

# --- Exit code ----------------------------------------------------------------
if ($setupErrors) { exit 2 } # Runner setup exit 2 is not scorer PARTIAL.
if ($unverified) { exit 3 } # A permissive threshold cannot award an incomplete run.
if ($pct -ge $PassThreshold) {
    Write-Host "PASS (>= $PassThreshold%)"
    exit 0
} else {
    Write-Host "FAIL (< $PassThreshold%)"
    exit 1
}
