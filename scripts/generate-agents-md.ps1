#requires -Version 5.1
# Compatibility entry point; the implementation and template ship with the skill.
[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ProfilePath,
    [string]$AgentsDir,
    [string[]]$SkillsDir,
    [string]$Output,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '../plugins/agile-agents-core/skills/solution-profile-interview/scripts/generate-agents-md.ps1') @PSBoundParameters
