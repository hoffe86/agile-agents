#requires -Version 5.1
<#
.SYNOPSIS
    Install or update the Copilot CLI development agent suite into a target repo
    or central user workspace.

.DESCRIPTION
    Copies the repository contents (agents/, skills/, scripts/, eval/, …) into a
    target project repo (flattening agents/ and skills/ since the Copilot CLI
    does not support nested folders under .github/agents/ or .github/skills/),
    or copies the user-scope skills under user/skills/ into ~/.copilot/skills/.

.PARAMETER TargetPath
    Destination root. For -Scope repo: the target project repo root. For -Scope user:
    optional — defaults to $env:USERPROFILE\.copilot.

.PARAMETER Scope
    'repo' (default) or 'user'.

.PARAMETER Mode
    'install' (default) or 'update'. In install mode, preserve files
    (solution-profile.yaml) refuse to overwrite without -Force. In update
    mode, preserve files are written as <name>.new alongside the existing
    one and a MERGE NEEDED notice is printed.

.PARAMETER DryRun
    Print the plan as a table without writing anything.

.PARAMETER Force
    Allow overwriting preserve files in install mode.

.PARAMETER Help
    Show help and exit.

.EXAMPLE
    Install into a target repo:
      .\install.ps1 -TargetPath C:\src\my-project

.EXAMPLE
    Update existing install:
      .\install.ps1 -TargetPath C:\src\my-project -Mode update

.EXAMPLE
    Install user-scope skills (default ~/.copilot):
      .\install.ps1 -Scope user

.EXAMPLE
    Dry-run to preview:
      .\install.ps1 -TargetPath C:\src\my-project -DryRun
#>
[CmdletBinding()]
param(
    [string]$TargetPath,
    [ValidateSet('repo','user')][string]$Scope = 'repo',
    [ValidateSet('install','update')][string]$Mode = 'install',
    [switch]$DryRun,
    [switch]$Force,
    [switch]$Help
)

if ($Help) { Get-Help -Detailed $PSCommandPath; exit 0 }

$ErrorActionPreference = 'Stop'

# Files that must never be silently overwritten (user customises these).
$PreserveFiles = @('solution-profile.yaml')

# ── helpers ───────────────────────────────────────────────────────────────────
function Write-Color {
    param([string]$Text, [string]$Color = 'Gray')
    try { Write-Host $Text -ForegroundColor $Color } catch { Write-Host $Text }
}

function New-PlanRow {
    param([string]$Action, [string]$Source, [string]$Destination)
    [pscustomobject]@{ Action = $Action; Source = $Source; Destination = $Destination }
}

function Add-FilePlan {
    param([System.Collections.Generic.List[object]]$Plan, [string]$Src, [string]$Dst, [bool]$Preserve)
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $exists = Test-Path -LiteralPath $Dst
    $action = 'ADD'
    if ($exists) {
        if ($Preserve) {
            $action = if ($Mode -eq 'update') { 'MERGE' } elseif ($Force) { 'UPDATE' } else { 'PRESERVE' }
        } else {
            $action = 'UPDATE'
        }
    }
    [void]$Plan.Add((New-PlanRow $action $Src $Dst))
}

function Add-DirPlan {
    param(
        [System.Collections.Generic.List[object]]$Plan,
        [string]$SrcRoot,
        [string]$DstRoot
    )
    if (-not (Test-Path -LiteralPath $SrcRoot)) { return }
    Get-ChildItem -LiteralPath $SrcRoot -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($SrcRoot.Length).TrimStart('\','/')
        Add-FilePlan $Plan $_.FullName (Join-Path $DstRoot $rel) $false
    }
}

function Invoke-Plan {
    param([System.Collections.Generic.List[object]]$Plan)
    $added = 0; $updated = 0; $preserved = 0; $merged = 0
    foreach ($row in $Plan) {
        switch ($row.Action) {
            'PRESERVE' {
                Write-Color "  PRESERVE  $($row.Destination)" 'Cyan'
                $preserved++
                continue
            }
            'MERGE' {
                $newPath = "$($row.Destination).new"
                if (-not $DryRun) {
                    $dir = Split-Path -Parent $newPath
                    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
                    Copy-Item -LiteralPath $row.Source -Destination $newPath -Force
                }
                Write-Color "  MERGE     $newPath  (review against existing)" 'Cyan'
                $merged++
                continue
            }
            default {
                if (-not $DryRun) {
                    $dir = Split-Path -Parent $row.Destination
                    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
                    try {
                        Copy-Item -LiteralPath $row.Source -Destination $row.Destination -Force
                    } catch {
                        Write-Color "ERROR copying $($row.Source) -> $($row.Destination): $_" 'Red'
                        exit 1
                    }
                }
                if ($row.Action -eq 'ADD') {
                    Write-Color "  ADD       $($row.Destination)" 'Green'
                    $added++
                } else {
                    Write-Color "  UPDATE    $($row.Destination)" 'Yellow'
                    $updated++
                }
            }
        }
    }
    return [pscustomobject]@{ Added = $added; Updated = $updated; Preserved = $preserved; Merged = $merged }
}

# ── resolve sources ───────────────────────────────────────────────────────────
$repoSrc  = $PSScriptRoot
$userSrc  = Join-Path $PSScriptRoot 'user'
$workflowSrc = Join-Path $PSScriptRoot '.github\workflows\agents-md-sync.yml'

if ($Scope -eq 'repo' -and -not (Test-Path -LiteralPath (Join-Path $repoSrc 'agents'))) {
    Write-Color "ERROR: source not found: $(Join-Path $repoSrc 'agents')" 'Red'; exit 1
}
if ($Scope -eq 'user' -and -not (Test-Path -LiteralPath $userSrc)) {
    Write-Color "ERROR: source not found: $userSrc" 'Red'; exit 1
}

# ── resolve target ────────────────────────────────────────────────────────────
if ($Scope -eq 'user' -and -not $TargetPath) {
    $TargetPath = Join-Path $env:USERPROFILE '.copilot'
}
if (-not $TargetPath) {
    Write-Color "ERROR: -TargetPath is required for -Scope repo" 'Red'; exit 2
}
if (-not (Test-Path -LiteralPath $TargetPath)) {
    if ($DryRun) {
        Write-Color "NOTE: target does not exist (would be created): $TargetPath" 'Yellow'
    } else {
        New-Item -ItemType Directory -Path $TargetPath -Force | Out-Null
    }
}
$TargetPath = (Resolve-Path -LiteralPath $TargetPath).Path

if ($Scope -eq 'repo' -and -not (Test-Path -LiteralPath (Join-Path $TargetPath '.git'))) {
    Write-Color "WARNING: $TargetPath is not a git repository" 'Yellow'
}

# ── build plan ────────────────────────────────────────────────────────────────
$plan = New-Object 'System.Collections.Generic.List[object]'

if ($Scope -eq 'repo') {
    $dotGithubAgents   = Join-Path $TargetPath '.github\agents'
    $dotGithubSkills   = Join-Path $TargetPath '.github\skills'
    $dotGithubWorkflow = Join-Path $TargetPath '.github\workflows'

    # 1. agents/ → .github/agents (flat)
    $agentSrc = Join-Path $repoSrc 'agents'
    if (Test-Path -LiteralPath $agentSrc) {
        Get-ChildItem -LiteralPath $agentSrc -Filter '*.agent.md' -File | ForEach-Object {
            Add-FilePlan $plan $_.FullName (Join-Path $dotGithubAgents $_.Name) $false
        }
    }

    # 2. skills/<skill>/ → .github/skills/<skill>/ (preserve skill folder)
    $skillsSrc = Join-Path $repoSrc 'skills'
    if (Test-Path -LiteralPath $skillsSrc) {
        Get-ChildItem -LiteralPath $skillsSrc -Directory | ForEach-Object {
            Add-DirPlan $plan $_.FullName (Join-Path $dotGithubSkills $_.Name)
        }
        # Loose files at the root of skills/ (e.g. VENDORED.md)
        Get-ChildItem -LiteralPath $skillsSrc -File | ForEach-Object {
            Add-FilePlan $plan $_.FullName (Join-Path $dotGithubSkills $_.Name) $false
        }
    }

    # 3. Preserve-paths
    $preserveCopies = @(
        @{ Src = (Join-Path $repoSrc 'AGENTS.md');             Dst = (Join-Path $TargetPath 'AGENTS.md');             Preserve = $false },
        @{ Src = (Join-Path $repoSrc 'solution-profile.yaml'); Dst = (Join-Path $TargetPath 'solution-profile.yaml'); Preserve = $true  },
        @{ Src = (Join-Path $repoSrc 'docs\AGENTS-MD-MAPPING.md'); Dst = (Join-Path $TargetPath '.github\AGENTS-MD-MAPPING.md'); Preserve = $false }
    )
    foreach ($p in $preserveCopies) {
        Add-FilePlan $plan $p.Src $p.Dst $p.Preserve
    }
    Add-DirPlan $plan (Join-Path $repoSrc 'eval')    (Join-Path $TargetPath 'eval')
    Add-DirPlan $plan (Join-Path $repoSrc 'scripts') (Join-Path $TargetPath 'scripts')

    # 4. CI workflow (sourced from this repo's .github/workflows/)
    Add-FilePlan $plan $workflowSrc (Join-Path $dotGithubWorkflow 'agents-md-sync.yml') $false
}
else {
    # user scope: only skills
    $skillsSrc = Join-Path $userSrc 'skills'
    if (Test-Path -LiteralPath $skillsSrc) {
        Get-ChildItem -LiteralPath $skillsSrc -Directory | ForEach-Object {
            Add-DirPlan $plan $_.FullName (Join-Path $TargetPath "skills\$($_.Name)")
        }
    }
}

if ($plan.Count -eq 0) {
    Write-Color "Nothing to do (no source files found)." 'Yellow'
    exit 0
}

# ── enforce -Force for preserve files in install mode ─────────────────────────
if ($Mode -eq 'install' -and -not $Force -and -not $DryRun) {
    $conflicts = @($plan | Where-Object { $_.Action -eq 'PRESERVE' })
    if ($conflicts.Count -gt 0) {
        Write-Color "" ; Write-Color "PATH CONFLICT: the following preserve files already exist:" 'Red'
        $conflicts | ForEach-Object { Write-Color "  $($_.Destination)" 'Red' }
        Write-Color "Re-run with -Force to overwrite, or use -Mode update to write *.new alongside." 'Red'
        exit 3
    }
}

# ── execute ───────────────────────────────────────────────────────────────────
Write-Color ""
Write-Color "Scope:  $Scope" 'White'
Write-Color "Mode:   $Mode$( if ($DryRun) { ' (dry-run)' } )" 'White'
Write-Color "Target: $TargetPath" 'White'
Write-Color ""

if ($DryRun) {
    $plan | Sort-Object Action, Destination | Format-Table -AutoSize | Out-String | Write-Host
    Write-Color "Total planned: $($plan.Count) file(s)" 'White'
    exit 0
}

$result = Invoke-Plan -Plan $plan

# ── summary ───────────────────────────────────────────────────────────────────
Write-Color ""
Write-Color "─── Summary ───────────────────────────────" 'White'
Write-Color "  Added     : $($result.Added)" 'Green'
Write-Color "  Updated   : $($result.Updated)" 'Yellow'
Write-Color "  Preserved : $($result.Preserved)" 'Cyan'
Write-Color "  Merge new : $($result.Merged)" 'Cyan'
Write-Color "  Total     : $($plan.Count)" 'White'
Write-Color ""

if ($Scope -eq 'repo') {
    Write-Color "Next steps:" 'White'
    Write-Color "  1. Review/customise $TargetPath\solution-profile.yaml" 'Gray'
    Write-Color "  2. Run scripts\generate-agents-md.ps1 to (re)build AGENTS.md" 'Gray'
    if ($result.Merged -gt 0) {
        Write-Color "  3. MERGE NEEDED: diff *.new files against the existing ones, then delete the *.new" 'Yellow'
    }
} else {
    Write-Color "User-scope skills installed to $TargetPath\skills" 'Gray'
}

exit 0
