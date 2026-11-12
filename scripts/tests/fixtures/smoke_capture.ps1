# Exercise partial output while the controlled writer is still alive: no EOF.
param([string]$Runner, [string]$Python, [string]$Fixture, [string]$PidFile)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Runner, [ref]$null, [ref]$null)
$definition = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Initialize-SmokeProtection'
}, $false)
. ([scriptblock]::Create($definition.Extent.Text))
Initialize-SmokeProtection

$info = [System.Diagnostics.ProcessStartInfo]::new($Python)
$info.UseShellExecute = $false
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
foreach ($arg in @($Fixture, 'hold-output', $PidFile)) { $info.ArgumentList.Add($arg) }
$process = [System.Diagnostics.Process]::Start($info)
$capture = [GateSmokeOutput]::new($process)
try {
    $ready = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $PidFile) -and $ready.ElapsedMilliseconds -lt 5000) {
        Start-Sleep -Milliseconds 20
    }
    if (-not (Test-Path -LiteralPath $PidFile)) { throw 'Output fixture did not start.' }
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $text = $capture.Drain(1000)
    @{ text = $text; elapsed_ms = $watch.ElapsedMilliseconds; alive = -not $process.HasExited } |
        ConvertTo-Json -Compress
} finally {
    $capture.Dispose()
    if (-not $process.HasExited) { $process.Kill($true) }
    if (-not $process.WaitForExit(2000)) { throw 'Output fixture did not stop.' }
    $process.Dispose()
}
