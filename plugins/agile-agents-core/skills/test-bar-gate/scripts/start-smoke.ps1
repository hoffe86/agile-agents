# Internal smoke launcher. Establish OS ownership before running any user command;
# neither an early launcher exit nor inherited output handles can lose descendants.
param(
    [Parameter(Mandatory)][string]$ArgvJson,
    [Parameter(Mandatory)][string]$ReadyFile
)
$ErrorActionPreference = 'Stop'

if ($IsWindows) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class SmokeJob
{
    // Kept open until this helper exits; the kernel then kills every member.
    private static IntPtr job;
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits {
        public BasicLimits Basic;
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass,
        ref ExtendedLimits info, uint size);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    public static void Own()
    {
        job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        var limits = new ExtendedLimits();
        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway
        if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>()))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        using (var self = Process.GetCurrentProcess()) {
            if (!AssignProcessToJobObject(job, self.Handle))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
'@
    [SmokeJob]::Own()
} else {
    Add-Type -TypeDefinition @'
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class SmokeGroup
{
    [DllImport("libc", SetLastError = true)]
    private static extern int setpgid(int pid, int pgid);
    public static void Own()
    {
        if (setpgid(0, 0) != 0) throw new Win32Exception(Marshal.GetLastWin32Error());
    }
}
'@
    [SmokeGroup]::Own()
}

[System.IO.File]::WriteAllText($ReadyFile, 'ready')
if ([Console]::In.ReadLine() -cne 'start') {
    throw 'Smoke parent closed the control pipe before command launch.'
}
$argv = @($ArgvJson | ConvertFrom-Json)
$info = [System.Diagnostics.ProcessStartInfo]::new()
$info.FileName = $argv[0]
$info.UseShellExecute = $false
$info.WorkingDirectory = (Get-Location).Path
foreach ($arg in ($argv | Select-Object -Skip 1)) { $info.ArgumentList.Add($arg) }
$process = [System.Diagnostics.Process]::Start($info)
# Publish the actual command PID only after Start succeeds. Renaming the closed
# file makes the acknowledgment visible as a whole, not a partially written PID.
# Both paths live inside the parent's atomically created owner-only directory;
# any future publication staging file must remain inside that directory too.
[System.IO.File]::WriteAllText($ReadyFile, [string]$process.Id)
[System.IO.File]::Move($ReadyFile, "$ReadyFile.started")
$process.WaitForExit()
$code = $process.ExitCode
$process.Dispose()
exit $code
