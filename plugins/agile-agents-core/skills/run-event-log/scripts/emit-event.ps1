<#
.SYNOPSIS
    Append one structured JSON event to the current run's events.jsonl.

.DESCRIPTION
    Helper for the run-event-log skill. Validates supervisor-owned events and
    required fields per event_type,
    stamps timestamp = current UTC ISO 8601 with millisecond precision, and
    appends one JSON line to ${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl.
    Append-only — never rewrites past events. See ../SKILL.md for full conventions.

.EXAMPLE
    .\emit-event.ps1 -RunId 01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f `
        -Agent dev-lead -Phase coding -EventType phase_complete -Outcome success -DurationMs 184000
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RunId,
    [Parameter(Mandatory)] [string] $Agent,
    [Parameter(Mandatory)] [string] $Phase,
    [Parameter(Mandatory)] [string] $EventType,
    [string] $Outcome,
    [string] $ToolName,
    [string] $ArgsSummary,
    [string] $ErrorKind,
    [string] $CorrelationId,
    [string] $ParentEventId,
    [int]    $DurationMs = -1,
    [object] $Payload
)

$ErrorActionPreference = 'Stop'

function Write-StdErr([string]$msg) { [Console]::Error.WriteLine($msg) }

function Test-SafeText([string]$text) {
    $patterns = @(
        '\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
        '\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization|accountkey|sharedaccesssignature|connection[_-]?string)\b\s*[:=]\s*\S+',
        '\bbearer\s+[A-Z0-9._~+/=-]{8,}',
        '\b(?:gh[pousr]_[A-Z0-9]{20,}|github_pat_[A-Z0-9_]{20,}|sk-[A-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[A-Z0-9_-]{30,}|xox[baprs]-[A-Z0-9-]{10,})\b',
        '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        '\b(?:sig|signature)\s*=\s*[^&;\s]+',
        '\b(?:https?|ftp)://[^/\s:@]+:[^/@\s]+@'
    )
    foreach ($pattern in $patterns) {
        if ([regex]::IsMatch($text, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
            return $false
        }
    }
    $phone = [regex]::Match($text, '(?<!\w)\+?\d[\d .()-]{8,}\d(?!\w)')
    if ($phone.Success -and (($phone.Value -replace '\D', '').Length -ge 10)) {
        return $false
    }
    return $true
}

function Assert-AllowedKeys($value, [string[]]$allowed) {
    $allowedSet = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    foreach ($field in $allowed) { [void]$allowedSet.Add($field) }
    if ($value -isnot [System.Collections.IDictionary] -or
        @($value.Keys | Where-Object { -not $allowedSet.Contains([string]$_) }).Count -gt 0) {
        Write-StdErr "emit-event: event contains unsupported object fields"
        exit 1
    }
}

function Assert-SafeValues($value) {
    if ($value -is [string]) {
        if (-not (Test-SafeText $value)) {
            Write-StdErr "emit-event: event contains a string resembling a credential or personal identifier"
            exit 1
        }
    } elseif ($value -is [System.Collections.IDictionary]) {
        foreach ($key in $value.Keys) {
            Assert-SafeValues ([string]$key)
            Assert-SafeValues $value[$key]
        }
    } elseif ($value -is [array]) {
        foreach ($item in $value) { Assert-SafeValues $item }
    }
}

if ($RunId -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') {
    Write-StdErr "emit-event: -RunId must be a UUID"
    exit 1
}
if ($Agent -ne 'dev-lead') {
    Write-StdErr "emit-event: only dev-lead may emit events"
    exit 1
}
if ($Phase.Length -lt 1 -or $Phase.Length -gt 64) {
    Write-StdErr "emit-event: -Phase must be 1-64 characters"
    exit 1
}
if ($EventType -notin @('run_start','run_complete','phase_start','phase_complete',
        'tool_call','gate_check','handoff_received','error')) {
    Write-StdErr "emit-event: invalid -EventType"
    exit 1
}
if ($Outcome -and $Outcome -notin @('success','fail','partial')) {
    Write-StdErr "emit-event: invalid -Outcome"
    exit 1
}
if ($DurationMs -lt -1) {
    Write-StdErr "emit-event: -DurationMs must be non-negative"
    exit 1
}
if ($Payload -is [string]) {
    try {
        $Payload = ConvertFrom-Json -InputObject $Payload -AsHashtable -ErrorAction Stop
    } catch {
        Write-StdErr "emit-event: -Payload must be valid JSON object data"
        exit 1
    }
}
if ($null -ne $Payload -and $Payload -isnot [System.Collections.IDictionary]) {
    Write-StdErr "emit-event: -Payload must be a JSON object"
    exit 1
}

function Require-PayloadField([string]$field, [Type]$type = [string]) {
    if (-not $Payload.Contains($field) -or $Payload[$field] -isnot $type) {
        Write-StdErr "emit-event: $EventType payload requires $field as $($type.Name)"
        exit 1
    }
}

function Test-MetricSet($metrics) {
    if ($metrics -isnot [System.Collections.IDictionary]) { return $false }
    $allowedFields = @('calls','tokens_in','tokens_out','tokens_reasoning',
        'tokens_cache_read','tokens_total','aiu','duration_ms','models','usd')
    if (@($metrics.Keys | Where-Object { $_ -notin $allowedFields }).Count -gt 0) { return $false }
    foreach ($field in @('models','usd')) {
        if (-not $metrics.Contains($field)) { return $false }
    }
    $integerFields = @('calls','tokens_in','tokens_out','tokens_reasoning',
        'tokens_cache_read','tokens_total','duration_ms')
    foreach ($field in $integerFields) {
        if (-not $metrics.Contains($field) -or
            $metrics[$field] -isnot [ValueType] -or
            $metrics[$field] -is [bool] -or
            [double]$metrics[$field] -lt 0 -or
            [double]$metrics[$field] -ne [math]::Truncate([double]$metrics[$field])) {
            return $false
        }
    }
    if (-not $metrics.Contains('aiu') -or
        $metrics.aiu -isnot [ValueType] -or $metrics.aiu -is [bool] -or
        [double]$metrics.aiu -lt 0 -or -not [double]::IsFinite([double]$metrics.aiu)) {
        return $false
    }
    if ($metrics.models -isnot [array]) { return $false }
    foreach ($model in $metrics.models) {
        if ($model -isnot [string]) { return $false }
    }
    if ($null -ne $metrics.usd -and
        ($metrics.usd -isnot [ValueType] -or $metrics.usd -is [bool] -or
         [double]$metrics.usd -lt 0 -or -not [double]::IsFinite([double]$metrics.usd))) {
        return $false
    }
    return $true
}

function Test-CollectorUsage($usage, [string]$status) {
    if ($usage -isnot [System.Collections.IDictionary]) { return $false }
    $allowedFields = @('session_id','totals','by_phase','by_agent','usd',
        'usd_basis','unattributed','warnings','breaches')
    if (@($usage.Keys | Where-Object { $_ -notin $allowedFields }).Count -gt 0) { return $false }
    foreach ($field in @('session_id','totals','by_phase','by_agent','usd',
            'usd_basis','unattributed','warnings','breaches')) {
        if (-not $usage.Contains($field)) { return $false }
    }
    if ($usage.session_id -isnot [string] -or -not $usage.session_id -or
        $usage.usd_basis -isnot [string] -or -not $usage.usd_basis -or
        $usage.warnings -isnot [array] -or $usage.breaches -isnot [array] -or
        -not (Test-MetricSet $usage.totals) -or
        -not (Test-MetricSet $usage.unattributed)) {
        return $false
    }
    foreach ($field in @('by_phase','by_agent')) {
        if ($usage[$field] -isnot [System.Collections.IDictionary]) { return $false }
        foreach ($bucket in $usage[$field].Values) {
            if (-not (Test-MetricSet $bucket)) { return $false }
        }
    }
    $metricSets = @($usage.totals, $usage.unattributed) +
        @($usage.by_phase.Values) + @($usage.by_agent.Values)
    foreach ($metrics in $metricSets) {
        if ($status -eq 'measured' -and
            ($metrics.usd -isnot [ValueType] -or $metrics.usd -is [bool])) {
            return $false
        }
        if ($status -eq 'unmetered' -and $null -ne $metrics.usd) {
            return $false
        }
    }
    foreach ($diagnostic in @($usage.warnings) + @($usage.breaches)) {
        $diagnosticFields = @('scope','metric','actual','limit','phase')
        if ($diagnostic -isnot [System.Collections.IDictionary] -or
            @($diagnostic.Keys | Where-Object { $_ -notin $diagnosticFields }).Count -gt 0 -or
            $diagnostic.scope -notin @('per_run','per_phase') -or
            $diagnostic.metric -notin @('tokens','aiu','usd') -or
            $diagnostic.actual -isnot [ValueType] -or $diagnostic.actual -is [bool] -or
            $diagnostic.limit -isnot [ValueType] -or $diagnostic.limit -is [bool] -or
            [double]$diagnostic.actual -lt 0 -or [double]$diagnostic.limit -lt 0 -or
            ($diagnostic.Contains('phase') -and $diagnostic.phase -isnot [string]) -or
            (($diagnostic.scope -eq 'per_phase') -ne $diagnostic.Contains('phase'))) {
            return $false
        }
    }
    if ($null -ne $usage.usd -and
        ($usage.usd -isnot [ValueType] -or $usage.usd -is [bool] -or
         [double]$usage.usd -lt 0 -or -not [double]::IsFinite([double]$usage.usd))) {
        return $false
    }
    return $true
}

function Assert-EventPayload {
    if ($null -eq $Payload) {
        if ($EventType -in @('run_start','run_complete','gate_check','handoff_received','error')) {
            Write-StdErr "emit-event: event type requires payload"
            exit 1
        }
        return
    }
    switch ($EventType) {
        'run_start' { Assert-AllowedKeys $Payload @('requirement_summary','profile_loaded') }
        'run_complete' {
            Assert-AllowedKeys $Payload @('cost_summary','termination_reason')
            if ($Payload.Contains('termination_reason') -and
                ($Payload.termination_reason -isnot [string] -or -not $Payload.termination_reason.Trim())) {
                Write-StdErr "emit-event: termination_reason must be a non-empty string"
                exit 1
            }
            if ($Payload.cost_summary -isnot [System.Collections.IDictionary]) {
                Write-StdErr "emit-event: run_complete requires cost_summary object"
                exit 1
            }
            $summary = $Payload.cost_summary
            switch ($summary.status) {
                { $_ -in 'measured','unmetered' } {
                    Assert-AllowedKeys $summary @('status','source','usage')
                    if (-not (Test-CollectorUsage $summary.usage $summary.status)) {
                        Write-StdErr "emit-event: cost_summary does not match collector contract"
                        exit 1
                    }
                }
                'unavailable' { Assert-AllowedKeys $summary @('status','source','reason') }
                'disabled' { Assert-AllowedKeys $summary @('status','reason') }
                default {
                    Write-StdErr "emit-event: unsupported cost_summary status"
                    exit 1
                }
            }
        }
        'gate_check' {
            Assert-AllowedKeys $Payload @('gate','applicability','reason')
            if ($Payload.Contains('applicability') -and $Payload.applicability -ne 'not_applicable') {
                Write-StdErr "emit-event: gate applicability is unsupported"
                exit 1
            }
            if ($Payload.Contains('reason') -and
                ($Payload.reason -isnot [string] -or -not $Payload.reason.Trim())) {
                Write-StdErr "emit-event: gate reason must be a non-empty string"
                exit 1
            }
        }
        'handoff_received' { Assert-AllowedKeys $Payload @('from_agent','sentinel') }
        'error' {
            Assert-AllowedKeys $Payload @('message')
            if ($Payload.message -isnot [string] -or -not $Payload.message.Trim() -or $Payload.message.Length -gt 200) {
                Write-StdErr "emit-event: error requires a short non-empty payload.message"
                exit 1
            }
        }
        default {
            Write-StdErr "emit-event: event type does not support a payload"
            exit 1
        }
    }
}

# Per-event_type validation
switch ($EventType) {
    'run_start' {
        if ($Outcome) { Write-StdErr "emit-event: run_start forbids -Outcome"; exit 1 }
        Require-PayloadField 'requirement_summary'
        Require-PayloadField 'profile_loaded' ([bool])
        if (-not $Payload.requirement_summary.Trim() -or $Payload.requirement_summary.Length -gt 200) {
            Write-StdErr "emit-event: requirement_summary must contain 1-200 characters"
            exit 1
        }
    }
    'run_complete' {
        if (-not $Outcome) { Write-StdErr "emit-event: run_complete requires -Outcome"; exit 1 }
        Require-PayloadField 'cost_summary' ([System.Collections.IDictionary])
        $summary = $Payload.cost_summary
        switch ($summary.status) {
            { $_ -in 'measured','unmetered' } {
                if ($summary.source -ne 'collect-usage.py' -or
                    -not (Test-CollectorUsage $summary.usage $summary.status)) {
                    Write-StdErr "emit-event: measured cost_summary requires collect-usage.py source and usage object"
                    exit 1
                }
                if ($summary.status -eq 'measured' -and
                    ($null -eq $summary.usage.usd -or
                     $summary.usage.usd -isnot [ValueType] -or
                     $summary.usage.usd -is [bool] -or
                     -not "$($summary.usage.usd_basis)".StartsWith('rate:'))) {
                    Write-StdErr "emit-event: measured cost_summary requires rated numeric USD"
                    exit 1
                }
                if ($summary.status -eq 'unmetered' -and
                    ($null -ne $summary.usage.usd -or $summary.usage.usd_basis -ne 'not-metered')) {
                    Write-StdErr "emit-event: unmetered cost_summary requires null USD and not-metered basis"
                    exit 1
                }
            }
            'unavailable' {
                if ($summary.source -ne 'collect-usage.py' -or
                    $summary.reason -isnot [string] -or -not $summary.reason.Trim()) {
                    Write-StdErr "emit-event: unavailable cost_summary requires source and reason"
                    exit 1
                }
            }
            'disabled' {
                if ($summary.reason -isnot [string] -or -not $summary.reason.Trim()) {
                    Write-StdErr "emit-event: disabled cost_summary requires a reason"
                    exit 1
                }
            }
            default {
                Write-StdErr "emit-event: cost_summary status must be measured, unmetered, unavailable, or disabled"
                exit 1
            }
        }
        if ($Outcome -in 'fail','partial' -and
            ($Payload.termination_reason -isnot [string] -or
             -not $Payload.termination_reason.Trim())) {
            Write-StdErr "emit-event: non-success run_complete requires a string payload.termination_reason"
            exit 1
        }
    }
    'phase_start' {
        if ($Outcome) { Write-StdErr "emit-event: phase_start forbids -Outcome"; exit 1 }
    }
    'phase_complete' {
        if (-not $Outcome) { Write-StdErr "emit-event: phase_complete requires -Outcome"; exit 1 }
    }
    'gate_check' {
        if (-not $Outcome) { Write-StdErr "emit-event: gate_check requires -Outcome"; exit 1 }
        Require-PayloadField 'gate'
        if (-not $Payload.gate.Trim()) {
            Write-StdErr "emit-event: gate_check payload.gate must not be empty"
            exit 1
        }
        if ($Payload.gate -eq 'test_bar' -and $Outcome -eq 'partial' -and
            ($Payload.applicability -ne 'not_applicable' -or
             -not "$($Payload.reason)".Trim())) {
            Write-StdErr "emit-event: partial test_bar requires not_applicable applicability and a reason"
            exit 1
        }
    }
    'handoff_received' {
        Require-PayloadField 'from_agent'
        Require-PayloadField 'sentinel'
        if (-not "$($Payload.from_agent)".Trim() -or -not "$($Payload.sentinel)".Trim()) {
            Write-StdErr "emit-event: handoff_received payload fields must not be empty"
            exit 1
        }
        if ($Payload.from_agent -notin @('architect','backlog-manager','bootstrapper',
                'capability-scout','coding','data-scientist','infrastructure','review-lead',
                'code-reviewer','security-reviewer','architecture-reviewer',
                'infrastructure-reviewer','test-reviewer','data-reviewer')) {
            Write-StdErr "emit-event: payload.from_agent must identify a worker"
            exit 1
        }
    }
    'tool_call' {
        if (-not $ToolName) { Write-StdErr "emit-event: tool_call requires -ToolName"; exit 1 }
    }
    'error' {
        if (-not $ErrorKind) { Write-StdErr "emit-event: error requires -ErrorKind"; exit 1 }
    }
}
Assert-EventPayload
foreach ($text in @($RunId,$Phase,$ToolName,$ArgsSummary,$ErrorKind,$CorrelationId,$ParentEventId)) {
    if ($text -and -not (Test-SafeText $text)) {
        Write-StdErr "emit-event: event contains a string resembling a credential or personal identifier"
        exit 1
    }
}
Assert-SafeValues $Payload
if ($ArgsSummary -and $ArgsSummary.Length -gt 200) {
    $ArgsSummary = $ArgsSummary.Substring(0, 200)
}

# Build event with insertion-ordered keys
$evt = [ordered]@{
    schema_version = 2
    timestamp  = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    run_id     = $RunId
    agent      = $Agent
    phase      = $Phase
    event_type = $EventType
}
if ($CorrelationId)            { $evt.correlation_id  = $CorrelationId }
if ($ParentEventId)            { $evt.parent_event_id = $ParentEventId }
if ($Outcome)                  { $evt.outcome         = $Outcome }
if ($DurationMs -ge 0)         { $evt.duration_ms     = $DurationMs }
if ($ToolName)                 { $evt.tool_name       = $ToolName }
if ($ArgsSummary)              { $evt.args_summary    = $ArgsSummary }
if ($ErrorKind)                { $evt.error_kind      = $ErrorKind }
if ($Payload)                  { $evt.payload         = $Payload }

$baseDir = if ($env:COPILOT_RUNS_DIR) { $env:COPILOT_RUNS_DIR } else { ".copilot-runs" }
$runDir  = Join-Path $baseDir $RunId
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Force -Path $runDir | Out-Null }
$file = Join-Path $runDir "events.jsonl"

# Compress to single line; UTF-8 without BOM; LF terminator
$json = ($evt | ConvertTo-Json -Compress -Depth 30)
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::AppendAllText($file, $json + "`n", $utf8NoBom)
exit 0