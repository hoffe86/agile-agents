#Requires -Version 7.0
# Thin argument translator. Python owns validation, inventory, staging and provenance.
# No parameter binder: missing/unknown arguments must reach argparse's exit 2.
$ErrorActionPreference = 'Stop'
$python = Get-Command python, python3 -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $python) {
    [Console]::Error.WriteLine('ERROR: Python is required. Install Python and put its interpreter on PATH; no evaluation started.')
    exit 2
}
$translated = @('-I', '-S', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'run_eval.py'))
$names = @{
    '-Suite' = '--suite'; '-TaskFilter' = '--task-filter'; '-PassThreshold' = '--pass-threshold'
    '-OutputRoot' = '--output-root'; '-AgentModel' = '--agent-model'; '-JudgeModel' = '--judge-model'
    '-Scorer' = '--scorer'; '-DryRun' = '--dry-run'; '-NoIsolation' = '--no-isolation'
    '-Help' = '--help'
}
for ($index = 0; $index -lt $args.Count; $index++) {
    $value = [string]$args[$index]
    if ($names.ContainsKey($value)) {
        $value = $names[$value]
        if ($value -notin @('--dry-run', '--no-isolation', '--help') -and
            $index + 1 -lt $args.Count -and -not $names.ContainsKey([string]$args[$index + 1])) {
            $index++
            $value += "=$($args[$index])"
        }
    }
    $translated += $value
}
& $python.Source @translated
exit $LASTEXITCODE
