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
    #   shell    — score-judge.{ps1,sh}: reads an inlined artifact dump, loads no skills.
    #              Retained for reproducing pre-cutover numbers, not for new measurement.
    #   both     — run each and record whether they agree.
    # The exit contract (0 resolved / 2 partial / 1 failed) is identical for all of them.
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

if (-not $DryRun -and -not (Get-Command copilot -ErrorAction SilentlyContinue)) {
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

if ($isolate -and -not $DryRun) {
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
} elseif ($isolate) {
    Write-Host "Config:    isolated ($isolatedHome) — plugins and MCP servers come only from --plugin-dir"
} else {
    Write-Host "Config:    NOT ISOLATED — user plugins shadow --plugin-dir; this does not measure the working tree" -ForegroundColor Yellow
}
Write-Host ''

# --- Execute each task --------------------------------------------------------
$results = @()
$scorerComparison = @()
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
            # A dry run never invoked the agent, so there is nothing to grade. Marking
            # these 'failed' (as this did) is a lie in the honest-looking direction: the
            # log reads "Failed: N/N" while the job exits 0 because the threshold was
            # set low, so a wiring check and a total collapse look identical.
            $status = 'skipped'
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
                # Both judges invoke the CLI, so both run under the same isolation — a
                # judge loading a different plugin set than the agent would grade against
                # conventions the agent never saw.
                $shellStatus = $null
                $deepStatus  = $null

                if ($Scorer -in @('shell', 'both')) {
                    Invoke-WithIsolation {
                        & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'score-judge.ps1') -Workspace $ws -AcceptancePath $acceptance -JudgeModel $JudgeModel *>> $logPath
                    }
                    $shellStatus = switch ($LASTEXITCODE) { 0 { 'resolved' } 2 { 'partial' } default { 'failed' } }
                }

                if ($Scorer -in @('deepeval', 'both')) {
                    $scoreWorkspace = Join-Path $repoRoot 'eval/deepeval/score_workspace.py'
                    $deepArgs = @($scoreWorkspace, $ws, $acceptance, '--model', $JudgeModel)
                    if ($isolatedHome) { $deepArgs += @('--isolated-home', $isolatedHome) }
                    # No Invoke-WithIsolation here: the scorer takes the isolated home as an
                    # argument and sets it on the child itself, so the redirect cannot leak.
                    & python @deepArgs *>> $logPath
                    $deepStatus = switch ($LASTEXITCODE) { 0 { 'resolved' } 2 { 'partial' } default { 'failed' } }
                }

                if ($Scorer -eq 'both') {
                    $agree = $shellStatus -eq $deepStatus
                    $line = "[scorer] shell=$shellStatus deepeval=$deepStatus agree=$agree"
                    $line | Add-Content -Path $logPath -Encoding utf8
                    Write-Host "     $line"
                    $scorerComparison += [ordered]@{
                        task = $task.Id; shell = $shellStatus; deepeval = $deepStatus; agree = $agree
                    }
                    # The shell judge stays authoritative while comparing, so a disagreement
                    # cannot silently move the headline score during the evaluation itself.
                    $status = $shellStatus
                }
                else {
                    $status = if ($Scorer -eq 'deepeval') { $deepStatus } else { $shellStatus }
                }
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
$skipped  = @($results | Where-Object { $_.status -eq 'skipped'  }).Count
$pct      = if ($total -gt 0) { [math]::Round(100.0 * $resolved / $total, 1) } else { 0 }

$summary = [ordered]@{
    suite        = $Suite
    run_id       = $runId
    total        = $total
    resolved     = $resolved
    partial      = $partial
    failed       = $failed
    skipped      = $skipped
    dry_run      = [bool]$DryRun
    scorer       = $Scorer
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
$summary | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $runDir 'summary.json') -Encoding utf8

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
    Write-Host ('Summary:  {0}' -f (Join-Path $runDir 'summary.json'))
    Write-Host 'Re-run without -DryRun to produce an actual score.'
    exit 0
}

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
