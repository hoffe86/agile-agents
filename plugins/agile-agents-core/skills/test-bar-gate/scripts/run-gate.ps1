<#
.SYNOPSIS
    Test-bar gate runner (PowerShell).

.DESCRIPTION
    Runs the checks declared under `quality_gates.test_bar` in solution-profile.yaml,
    in order, fail-fast by default:

        lint -> typecheck -> unit_test -> integration_test -> coverage -> mutation -> smoke

    Enabled checks require solution-declared commands; no language defaults.
    The smoke slot comes from `testing.smoke`: start, poll, always stop.
    Missing setup exits 2, never success. Non-runnable projects require
    -SmokeStatus not_applicable -SmokeDetail "evidence inspected".

    Emits gate_check events to $env:COPILOT_EVENT_LOG (or stdout) and prints a
    markdown failure report on the first failing check.

    Exit codes:
      0 = all checks passed, or the gate was skipped
      1 = at least one check failed
      2 = configuration gap (including unresolved smoke)

.PARAMETER ProfilePath
    Explicit profile path. Defaults to .github/solution-profile.yaml.
    Missing or invalid profiles exit 2.

.PARAMETER SmokeCommand
    Start command for the smoke slot, overriding testing.smoke.command. Carries the
    entry point the caller discovered when the profile does not declare one — see
    references/startup-discovery.md.

.PARAMETER SmokeUrl
    Health URL for the smoke slot, overriding testing.smoke.url.

.NOTES
    Requires `ConvertFrom-Yaml` (powershell-yaml module) to read the profile.
    Install with: Install-Module powershell-yaml
#>
[CmdletBinding()]
param(
    [string]$ProfilePath = '',
    [string]$SmokeCommand = '',
    [string]$SmokeUrl = '',
    [string]$SmokeStatus = '',
    [string]$SmokeDetail = ''
)

$ErrorActionPreference = 'Stop'

$CheckOrder = @('lint', 'typecheck', 'unit_test', 'integration_test', 'coverage', 'mutation')
# Checks that are on unless the profile says otherwise.
$DefaultEnabled = @{ lint = $true; typecheck = $true; unit_test = $true }

function Read-Yaml([string]$Path, [switch]$Required) {
    if (-not (Test-Path $Path)) {
        if ($Required) { throw "Required YAML file not found: $Path" }
        return @{}
    }
    if (-not (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue)) {
        throw "ConvertFrom-Yaml is unavailable. Install it with: Install-Module powershell-yaml"
    }
    $parsed = Get-Content -Raw $Path | ConvertFrom-Yaml
    if ($null -eq $parsed) { return @{} }
    return $parsed
}

function Emit-Event([hashtable]$evt) {
    $json = ($evt | ConvertTo-Json -Compress -Depth 6)
    if ($env:COPILOT_EVENT_LOG) {
        Add-Content -Path $env:COPILOT_EVENT_LOG -Value $json
    } else {
        Write-Host $json
    }
}

# Reads a nested key without throwing when an intermediate level is absent.
function Get-Node($root, [string[]]$Path) {
    $node = $root
    foreach ($segment in $Path) {
        if ($null -eq $node) { return $null }
        if ($node -is [System.Collections.IDictionary]) {
            if (-not $node.Contains($segment)) { return $null }
            $node = $node[$segment]
        } else {
            $prop = $node.PSObject.Properties[$segment]
            if (-not $prop) { return $null }
            $node = $prop.Value
        }
    }
    return $node
}

# Strings retain whitespace splitting. Use a list for arguments containing spaces.
function ConvertTo-Argv($value) {
    if ($null -eq $value) { return @() }
    if ($value -is [string]) {
        if ([string]::IsNullOrWhiteSpace($value)) { return @() }
        return @($value -split '\s+' | Where-Object { $_ })
    }
    return @($value | ForEach-Object { "$_" })
}

function Test-CommandValue($value) {
    if ($null -eq $value -or $value -is [string]) { return $true }
    if ($value -isnot [System.Collections.IList]) { return $false }
    foreach ($arg in $value) {
        if ($arg -isnot [string] -or $arg -match '[\r\n]') { return $false }
    }
    return $true
}

function Write-FailureReport([string]$name, [string]$cmdline, $exitCode, [string]$tail, [string]$reason) {
    Write-Host ""
    Write-Host "**Test-bar gate failed: $name**"
    Write-Host ""
    Write-Host "- **Command run:** ``$cmdline``"
    Write-Host "- **Exit code:** $exitCode"
    if ($reason) { Write-Host "- **Reason:** $reason" }
    Write-Host "- **Working directory:** $(Get-Location)"
    Write-Host ""
    Write-Host "### stderr (last 30 lines)`n`n``````text`n$tail`n``````"
    Write-Host ""
    Write-Host "### Suggested next action`n`nReturn to ``coding`` (or ``infrastructure`` when the diff is IaC-only) with this report. Up to three corrective retries are allowed; if the gate still fails, halt and ask the user."
}

function Write-ConfigurationGap([string]$name, [string]$detail, [string]$reason = 'configuration_gap') {
    Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; reason=$reason; exit_code=2; detail=$detail }
    Write-FailureReport $name '' 2 $detail $reason
}

# ProcessStartInfo preserves argv boundaries (Start-Process flattens ArgumentList).
# Drain both streams concurrently so a noisy child cannot deadlock the runner.
function Start-GateProcess([string[]]$argv, [switch]$Smoke) {
    $readyFile = $null
    if ($Smoke) {
        # Establish ownership before the launcher can spawn/exit. The helper
        # inherits our pipes and preserves the command's native exit code.
        $executable = Get-Command $argv[0] -CommandType Application -ErrorAction Stop
        $argv[0] = $executable.Source
        $json = ConvertTo-Json -InputObject @($argv) -Compress
        $readyFile = [GateSmokeRendezvous]::Create()
        $argv = @((Get-Process -Id $PID).Path, '-NoProfile', '-NonInteractive',
            '-File', (Join-Path $PSScriptRoot 'start-smoke.ps1'), $json, $readyFile)
    }
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $argv[0]
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = [bool]$Smoke
    $info.WorkingDirectory = (Get-Location).Path
    foreach ($arg in ($argv | Select-Object -Skip 1)) { $info.ArgumentList.Add($arg) }
    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $info
    try { [void]$proc.Start() } catch {
        $proc.Dispose()
        if ($readyFile) { [GateSmokeRendezvous]::Delete($readyFile) }
        throw
    }
    if ($Smoke) {
        return @{ Process = $proc; Capture = [GateSmokeOutput]::new($proc); ReadyFile = $readyFile }
    }
    return @{ Process = $proc; Output = $proc.StandardOutput.ReadToEndAsync()
        Error = $proc.StandardError.ReadToEndAsync() }
}

function Stop-GateProcess($child) {
    if ($child) {
        $proc = $child.Process
        if (-not $proc.HasExited) { $proc.Kill($true) }
        [void]$proc.WaitForExit(2000)
        $proc.Dispose()
    }
}

# PowerShell's finally and ProcessExit are not reliable on Unix SIGTERM.
# Register the actual signal; scriptblock callbacks have no runspace on that
# thread. This is lifecycle plumbing, not a second command runner.
function Initialize-SmokeProtection {
    if (-not ('GateSmokeLifetime' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

// .NET 6 has no Unix-mode CreateDirectory overload. Use the OS primitives to
// establish privacy at creation, never mkdir-then-chmod or an unreserved sibling.
public static class GateSmokeRendezvous
{
    [DllImport("libc", SetLastError = true)]
    private static extern IntPtr mkdtemp([In, Out] byte[] template);
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes {
        public int Length;
        public IntPtr Descriptor;
        public int InheritHandle;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateDirectoryW(string path, ref SecurityAttributes attributes);

    public static string Create()
    {
        string directory;
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) {
            directory = Path.Combine(Path.GetTempPath(), "gate-smoke-" + Guid.NewGuid().ToString("N"));
            using (var identity = WindowsIdentity.GetCurrent()) {
                var security = new DirectorySecurity();
                security.SetOwner(identity.User);
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new FileSystemAccessRule(identity.User, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None, AccessControlType.Allow));
                var descriptor = GCHandle.Alloc(security.GetSecurityDescriptorBinaryForm(), GCHandleType.Pinned);
                try {
                    var attributes = new SecurityAttributes {
                        Length = Marshal.SizeOf<SecurityAttributes>(),
                        Descriptor = descriptor.AddrOfPinnedObject()
                    };
                    // Exclusive creation: never reuse an existing directory.
                    if (!CreateDirectoryW(directory, ref attributes))
                        throw new Win32Exception(Marshal.GetLastWin32Error());
                } finally { descriptor.Free(); }
                try {
                    // Filesystems that ignore ACLs must fail before any file or
                    // helper is created. Do not repair permissions after creation.
                    var actual = new DirectoryInfo(directory).GetAccessControl(AccessControlSections.Access);
                    var rules = actual.GetAccessRules(true, true, typeof(SecurityIdentifier));
                    var rule = rules.Count == 1 ? (FileSystemAccessRule)rules[0] : null;
                    if (!actual.AreAccessRulesProtected || rule == null || rule.IsInherited ||
                        !identity.User.Equals(rule.IdentityReference) ||
                        rule.AccessControlType != AccessControlType.Allow ||
                        rule.FileSystemRights != FileSystemRights.FullControl ||
                        rule.InheritanceFlags != (InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit) ||
                        rule.PropagationFlags != PropagationFlags.None)
                        throw new IOException("Private smoke directory ACL was not preserved.");
                } catch {
                    Directory.Delete(directory);
                    throw;
                }
            }
        } else {
            var template = Encoding.UTF8.GetBytes(Path.Combine(Path.GetTempPath(), "gate-smoke-XXXXXX") + "\0");
            // POSIX mkdtemp atomically creates a new directory with mode 0700.
            if (mkdtemp(template) == IntPtr.Zero)
                throw new Win32Exception(Marshal.GetLastWin32Error());
            directory = Encoding.UTF8.GetString(template, 0, template.Length - 1);
        }
        string readyFile = Path.Combine(directory, "ready");
        try {
            using (File.Create(readyFile)) { }
            return readyFile;
        } catch {
            Delete(readyFile);
            throw;
        }
    }
    public static void Delete(string readyFile)
    {
        // Only our known files; never recursively delete an arbitrary temp tree.
        string directory = Path.GetDirectoryName(readyFile);
        if (!Directory.Exists(directory)) return; // Lifetime and finally both clean up.
        File.Delete(readyFile);
        File.Delete(readyFile + ".started");
        Directory.Delete(directory);
    }
}

// Keep partial chunks, not just completed lines or an EOF-dependent string.
public sealed class GateSmokeOutput : IDisposable
{
    private readonly CancellationTokenSource cancel = new CancellationTokenSource();
    private readonly StringBuilder output = new StringBuilder();
    private readonly StringBuilder error = new StringBuilder();
    private readonly Task readers;
    public GateSmokeOutput(Process process)
    {
        readers = Task.WhenAll(Read(process.StandardOutput, output),
            Read(process.StandardError, error));
    }
    private async Task Read(StreamReader reader, StringBuilder target)
    {
        var buffer = new char[4096];
        try {
            int count;
            while ((count = await reader.ReadAsync(buffer.AsMemory(), cancel.Token)) != 0) {
                lock (target) { target.Append(buffer, 0, count); }
            }
        } catch (OperationCanceledException) when (cancel.IsCancellationRequested) {
            // Bounded drain expired; retain everything already read.
        } catch (ObjectDisposedException) when (cancel.IsCancellationRequested) {
            // Process disposal closes its pipes after cancellation.
        }
    }
    public string Drain(int timeoutMs)
    {
        bool complete = readers.Wait(timeoutMs);
        string stdout, stderr;
        lock (output) { stdout = output.ToString(); }
        lock (error) { stderr = error.ToString(); }
        return stdout + "\n" + stderr + (complete ? "" :
            "\nsmoke output drain timed out; reporting available output");
    }
    public void Dispose() { cancel.Cancel(); }
}

public sealed class GateSmokeLifetime : IDisposable
{
    private readonly Process process;
    private readonly int processId;
    private readonly string readyFile;
    private readonly object sync = new object();
    private bool stopped;
    private readonly PosixSignalRegistration terminate;
    private readonly PosixSignalRegistration interrupt;
    [DllImport("libc", SetLastError = true)]
    private static extern int kill(int pid, int signal);
    public GateSmokeLifetime(Process process, string readyFile)
    {
        this.process = process;
        processId = process.Id;
        this.readyFile = readyFile;
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) {
            terminate = PosixSignalRegistration.Create(PosixSignal.SIGTERM,
                context => OnSignal(context, 143));
            interrupt = PosixSignalRegistration.Create(PosixSignal.SIGINT,
                context => OnSignal(context, 130));
        }
    }
    public void Stop()
    {
        lock (sync) {
            if (stopped) return;
            try {
                // Stop the helper first so it cannot create a new group/child
                // after cleanup. Windows closes its kill-on-close job here.
                if (!process.HasExited) process.Kill(true);
            } catch (InvalidOperationException) when (process.HasExited) {
                // The helper exited between the liveness check and Kill.
            }
            if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) {
                // Group ownership survives launcher exit and reparenting.
                // ESRCH means the group is already gone, not a cleanup failure.
                if (kill(-processId, 9) != 0 && Marshal.GetLastWin32Error() != 3)
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            if (!process.WaitForExit(2000))
                throw new TimeoutException("Smoke helper did not stop within 2 seconds.");
            GateSmokeRendezvous.Delete(readyFile);
            stopped = true;
        }
    }
    private void OnSignal(PosixSignalContext context, int exitCode)
    {
        context.Cancel = true;
        Stop();
        Environment.Exit(exitCode);
    }
    public void Dispose()
    {
        terminate?.Dispose();
        interrupt?.Dispose();
        Stop();
    }
}
'@
    }
}

function Invoke-Check([string]$name, [string[]]$argv) {
    $cmdline = ($argv -join ' ')
    Write-Host "-> $name : $cmdline"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $child = $null
    try {
        try {
            $child = Start-GateProcess $argv
        } catch {
            # An uninstalled toolchain is the most common gate failure on a fresh
            # machine. Report it through the normal contract instead of throwing.
            $sw.Stop()
            $msg = "command not found: $($argv[0])"
            Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; command=$cmdline; exit_code=127; stderr_tail=$msg; reason='command_not_found' }
            Write-FailureReport $name $cmdline 127 $msg 'command_not_found'
            return $false
        }
        $child.Process.WaitForExit()
        $sw.Stop()
        Write-Host $child.Output.GetAwaiter().GetResult()
        $stderr = $child.Error.GetAwaiter().GetResult()
        if ($stderr) { [Console]::Error.Write($stderr) }
        $exit = $child.Process.ExitCode
        if ($exit -eq 0) {
            Emit-Event @{ event_type='gate_check'; check=$name; outcome='success'; command=$cmdline; duration_ms=$sw.ElapsedMilliseconds }
            return $true
        }
        $tail = ($stderr -split "`n" | Select-Object -Last 30) -join "`n"
        Emit-Event @{ event_type='gate_check'; check=$name; outcome='fail'; command=$cmdline; exit_code=$exit; stderr_tail=$tail }
        Write-FailureReport $name $cmdline $exit $tail
        return $false
    } finally {
        Stop-GateProcess $child
    }
}

# Runnable projects must start; absence of setup is not non-applicability.
function Invoke-Smoke($profile) {
    # CLI overrides win: they carry the entry point the agent discovered when the
    # profile does not declare one (see references/startup-discovery.md).
    if ($SmokeCommand) {
        $argv = @(ConvertTo-Argv $SmokeCommand)
        $url = if ($SmokeUrl) { $SmokeUrl } else { Get-Node $profile @('testing', 'smoke', 'url') }
    }
    else {
        $value = Get-Node $profile @('testing', 'smoke', 'command')
        if (-not (Test-CommandValue $value)) {
            Write-ConfigurationGap smoke 'testing.smoke.command must be a string or list of single-line strings.'
            return 2
        }
        $argv = @(ConvertTo-Argv $value)
        $url = if ($SmokeUrl) { $SmokeUrl } else { Get-Node $profile @('testing', 'smoke', 'url') }
    }
    if ($SmokeStatus) {
        if ([string]::IsNullOrWhiteSpace($SmokeDetail) -or $SmokeStatus -cnotin @('not_applicable', 'undetermined')) {
            Write-ConfigurationGap smoke 'Smoke status requires not_applicable/undetermined and nonblank evidence detail.'
            return 2
        }
        if ($SmokeStatus -ceq 'undetermined') {
            Write-ConfigurationGap smoke $SmokeDetail undetermined
            return 2
        }
        if ($argv.Count -gt 0 -or $url) {
            Write-ConfigurationGap smoke 'not_applicable conflicts with configured smoke command/URL.'
            return 2
        }
        Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='skipped'; reason='not_applicable'; detail=$SmokeDetail }
        return 0
    }
    if ($argv.Count -eq 0 -or [string]::IsNullOrWhiteSpace($argv[0]) -or [string]::IsNullOrWhiteSpace($url)) {
        Write-ConfigurationGap smoke 'Resolve testing.smoke.command and url from solution evidence; or supply a not_applicable status with evidence.' needs_discovery
        return 2
    }
    $timeout = Get-Node $profile @('testing', 'smoke', 'timeout_s')
    if ($null -eq $timeout) { $timeout = 60 }
    if ("$timeout" -notmatch '^[1-9][0-9]*$') {
        Write-ConfigurationGap smoke 'testing.smoke.timeout_s must be a positive integer.'
        return 2
    }
    if ($url -cnotmatch '^https?://') {
        Write-ConfigurationGap smoke 'An HTTP(S) health URL is required.'
        return 2
    }
    if (-not ('System.Runtime.InteropServices.PosixSignalRegistration' -as [type])) {
        Write-ConfigurationGap smoke 'Smoke cleanup requires PowerShell 7.2+ (.NET 6+).'
        return 2
    }

    $cmdline = ($argv -join ' ')
    Write-Host "-> smoke : $cmdline (polling $url, timeout ${timeout}s)"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $child = $null
    $lifetime = $null
    $commandProcess = $null
    Initialize-SmokeProtection
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        try {
            $child = Start-GateProcess $argv -Smoke
        } catch [System.Management.Automation.CommandNotFoundException] {
            $sw.Stop()
            $msg = "command not found: $($argv[0])"
            Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='fail'; command=$cmdline; exit_code=127; stderr_tail=$msg; reason='command_not_found' }
            Write-FailureReport 'smoke' $cmdline 127 $msg 'command_not_found'
            return 1
        } catch {
            $sw.Stop()
            $msg = "Smoke setup failed: $($_.Exception.Message)"
            Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='fail'; command=$cmdline; exit_code=1; stderr_tail=$msg; reason='smoke_setup_failed' }
            Write-FailureReport 'smoke' $cmdline 1 $msg 'smoke_setup_failed'
            return 1
        }
        $proc = $child.Process
        $lifetime = [GateSmokeLifetime]::new($proc, $child.ReadyFile)
        # Ownership setup has its own bounded budget, like Add-Type above.
        # Start the configured command's timeout only when the helper can launch
        # it; a slow/cold PowerShell startup must not consume that command budget.
        $setupDeadline = [System.Diagnostics.Stopwatch]::StartNew()
        while ((Get-Item -LiteralPath $child.ReadyFile).Length -eq 0 -and
                -not $proc.HasExited -and $setupDeadline.ElapsedMilliseconds -lt 5000) {
            Start-Sleep -Milliseconds 20
        }
        $ready = (Get-Item -LiteralPath $child.ReadyFile).Length -gt 0 -and -not $proc.HasExited
        if ($ready) {
            $proc.StandardInput.WriteLine('start')
            $proc.StandardInput.Close()
        }
        $deadline = (Get-Date).AddSeconds([int]$timeout)
        # Ownership is not launch evidence. Launch acknowledgment shares the
        # command's deadline; an already-reachable URL cannot bypass this wait.
        $startedFile = $child.ReadyFile + '.started'
        while ($ready -and -not [System.IO.File]::Exists($startedFile) -and
                -not $proc.HasExited -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 20
        }
        $launched = [System.IO.File]::Exists($startedFile)
        if ($launched -and -not $proc.HasExited) {
            $commandId = [int][System.IO.File]::ReadAllText($startedFile)
            try {
                $commandProcess = [System.Diagnostics.Process]::GetProcessById($commandId)
            } catch [System.ArgumentException] {
                # The acknowledged command already exited, not a live helper
                # standing in for a live application.
            }
        }
        $up = $false
        while ($commandProcess -and (Get-Date) -lt $deadline) {
            if ($proc.HasExited -or $commandProcess.HasExited) { break }
            $cancel = [System.Threading.CancellationTokenSource]::new()
            $resp = $null
            $reachable = $false
            try {
                $remaining = [Math]::Max(1, ($deadline - (Get-Date)).TotalMilliseconds)
                $cancel.CancelAfter([int]$remaining)
                # Headers suffice for reachability; do not follow redirects or
                # wait indefinitely for a response body from a starting server.
                $resp = $client.GetAsync($url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead,
                    $cancel.Token).GetAwaiter().GetResult()
                $reachable = [int]$resp.StatusCode -ge 100 -and [int]$resp.StatusCode -lt 500
            } catch {
                # Not listening yet - keep polling until the deadline.
            } finally {
                if ($resp) { $resp.Dispose() }
                $cancel.Dispose()
            }
            if ($reachable -and -not $proc.HasExited -and -not $commandProcess.HasExited) {
                $up = $true
                break
            }
            Start-Sleep -Milliseconds 200
        }
        $sw.Stop()
        if ($up) {
            Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='success'; command=$cmdline; duration_ms=$sw.ElapsedMilliseconds }
            return 0
        }
        $commandExited = $launched -and (-not $commandProcess -or $commandProcess.HasExited)
        if ($commandExited -and -not $proc.HasExited) {
            # Let the helper relay the native exit code, but never wait on it
            # indefinitely after observing the actual command's exit.
            [void]$proc.WaitForExit(2000)
        }
        $exitCode = if ($proc.HasExited) { $proc.ExitCode } else { 1 }
        $reason = if ($proc.HasExited) { "process exited with $($proc.ExitCode)" }
            elseif (-not $ready) { 'smoke ownership setup did not complete within 5s' }
            elseif (-not $launched) { "smoke command launch did not complete within ${timeout}s" }
            elseif ($commandExited) { 'command process exited before readiness' }
            else { "no response within ${timeout}s" }
        $lifetime.Stop()
        $combined = $child.Capture.Drain(2000)
        $tail = ($combined -split "`n" | Select-Object -Last 20) -join "`n"
        Emit-Event @{ event_type='gate_check'; check='smoke'; outcome='fail'; command=$cmdline; exit_code=$exitCode; stderr_tail=$tail; reason=$reason }
        Write-FailureReport 'smoke' $cmdline $exitCode $tail $reason
        return 1
    } finally {
        try {
            if ($lifetime) { $lifetime.Dispose() }
        } finally {
            try {
                if ($child -and $child.Capture) { $child.Capture.Dispose() }
                if ($commandProcess) { $commandProcess.Dispose() }
                Stop-GateProcess $child
            } finally {
                $client.Dispose()
                if ($child -and $child.ReadyFile) {
                    [GateSmokeRendezvous]::Delete($child.ReadyFile)
                }
            }
        }
    }
}

# --- main ---
try {
    if (-not $ProfilePath) {
        $ProfilePath = Join-Path (Get-Location) '.github/solution-profile.yaml'
    }
    $profile = Read-Yaml $ProfilePath -Required
    if ($profile -isnot [System.Collections.IDictionary] -or $profile.Count -eq 0) {
        throw "Profile must be a non-empty YAML mapping: $ProfilePath"
    }
} catch {
    [Console]::Error.WriteLine("test-bar-gate configuration error: " + $_.Exception.Message)
    exit 2
}

$gate = Get-Node $profile @('quality_gates', 'test_bar')
if ($gate -is [System.Collections.IDictionary] -and $gate.Contains('stacks')) {
    Write-ConfigurationGap resolve 'quality_gates.test_bar.stacks is unsupported; declare check commands.'
    exit 2
}

$gateEnabled = Get-Node $profile @('quality_gates', 'test_bar', 'enabled')
if ($null -ne $gateEnabled -and $gateEnabled -isnot [bool]) {
    Write-ConfigurationGap resolve 'quality_gates.test_bar.enabled must be boolean.'
    exit 2
}
if ($null -ne $gateEnabled -and -not [bool]$gateEnabled) {
    Emit-Event @{ event_type='gate_check'; check='resolve'; outcome='skipped'; reason='disabled_by_profile' }
    Write-Host "test-bar-gate: disabled by profile - gate skipped."
    exit 0
}

$failFast = $true
$ff = Get-Node $profile @('quality_gates', 'test_bar', 'fail_fast')
if ($null -ne $ff -and $ff -isnot [bool]) {
    Write-ConfigurationGap resolve 'quality_gates.test_bar.fail_fast must be boolean.'
    exit 2
}
if ($null -ne $ff) { $failFast = [bool]$ff }

$result = 0
$ranAnything = $false
foreach ($check in $CheckOrder) {
    $node = Get-Node $profile @('quality_gates', 'test_bar', $check)
    $explicit = Get-Node $node @('enabled')
    if ($null -ne $explicit -and $explicit -isnot [bool]) {
        Write-ConfigurationGap $check "quality_gates.test_bar.${check}.enabled must be boolean."
        $result = 2
        if ($failFast) { break }
        continue
    }
    $enabled = if ($null -ne $explicit) { $explicit } else { $DefaultEnabled.ContainsKey($check) }
    if (-not $enabled) {
        $reason = if ($null -ne $explicit) { 'disabled_by_profile' } else { 'disabled_by_default' }
        Emit-Event @{ event_type='gate_check'; check=$check; outcome='skipped'; reason=$reason }
        continue
    }
    $value = Get-Node $node @('command')
    if (-not (Test-CommandValue $value)) {
        Write-ConfigurationGap $check "quality_gates.test_bar.${check}.command must be a string or list of single-line strings."
        $result = 2
        if ($failFast) { break }
        continue
    }
    $argv = @(ConvertTo-Argv $value)
    if ($argv.Count -eq 0 -or [string]::IsNullOrWhiteSpace($argv[0])) {
        Write-ConfigurationGap $check "Enabled check requires quality_gates.test_bar.${check}.command from existing solution CI/scripts; no language defaults."
        $result = 2
        if ($failFast) { break }
        continue
    }
    $ranAnything = $true
    if (-not (Invoke-Check $check $argv)) {
        if ($result -ne 2) { $result = 1 }
        if ($failFast) { break }
    }
}

if ($result -eq 0 -or -not $failFast) {
    $smokeResult = Invoke-Smoke $profile
    $result = [Math]::Max($result, $smokeResult)
}

if ($result -eq 0) {
    if (-not $ranAnything -and $SmokeStatus -ceq 'not_applicable') {
        Emit-Event @{ event_type='gate_check'; check='summary'; outcome='skipped'; reason='no_checks_enabled' }
    } else {
        Emit-Event @{ event_type='gate_check'; check='summary'; outcome='success' }
    }
    exit 0
}
exit $result
