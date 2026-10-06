#Requires -Version 7.0
<#
.SYNOPSIS
Fail-closed scorer with shared offline outcome contract and fixture integrity checks.
Exit 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup or judge error.
#>
[CmdletBinding()]
param(
    [string]$Workspace,
    [string]$AcceptancePath,
    [string]$PromptTemplate = (Join-Path $PSScriptRoot 'references/judge-prompt.md'),
    [string]$JudgeModel = $(if ($env:JUDGE_MODEL) { $env:JUDGE_MODEL } else { 'gpt-5.6-sol' }),
    [string]$BaselineDirectory,
    [string]$ResultJson,
    [int]$Timeout = 900,
    [switch]$SelfTest
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    [Console]::Error.WriteLine('[judge] setup_error: python is required for structured grading.')
    Write-Output '[judge-result] {"schema_version":2,"status":"setup_error","exit_code":4,"error_kind":"setup","reasons":["python is required"],"normalized_verdict":"SETUP_ERROR","score":0,"raw_response_persisted":false}'
    exit 4
}
$judgeArgs = @((Join-Path $PSScriptRoot 'shell_judge.py'))
if ($SelfTest) {
    $judgeArgs += '--self-test'
} else {
    if (-not $Workspace -or -not $AcceptancePath) {
        & python @judgeArgs
        exit $LASTEXITCODE
    }
    $judgeArgs += @($Workspace, $AcceptancePath, '--prompt-template', $PromptTemplate,
                   '--model', $JudgeModel, '--timeout', "$Timeout")
    if ($BaselineDirectory) { $judgeArgs += @('--baseline-dir', $BaselineDirectory) }
    if ($ResultJson) { $judgeArgs += @('--result-json', $ResultJson) }
}
& python @judgeArgs
exit $LASTEXITCODE
