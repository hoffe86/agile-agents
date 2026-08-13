#!/usr/bin/env bash
# Append one structured JSON event to the current run's events.jsonl.
#
# Helper for the run-event-log skill. Validates required fields per event_type,
# stamps timestamp = current UTC ISO 8601 with millisecond precision, and
# appends one JSON line to "${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl".
# Append-only — never rewrites past events. See ../SKILL.md for full conventions.
#
# Usage:
#   ./emit-event.sh --run-id <uuid> --agent <name> --phase <name> --event-type <type> \
#       [--outcome success|fail|partial] [--tool-name <s>] [--args-summary <s>] \
#       [--error-kind <s>] [--correlation-id <s>] [--parent-event-id <s>] \
#       [--duration-ms <int>] [--payload-json <json-object>]

set -euo pipefail

run_id=""; agent=""; phase=""; event_type=""
outcome=""; tool_name=""; args_summary=""; error_kind=""
correlation_id=""; parent_event_id=""
duration_ms=""; payload_json=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-id)          run_id="$2"; shift 2 ;;
        --agent)           agent="$2"; shift 2 ;;
        --phase)           phase="$2"; shift 2 ;;
        --event-type)      event_type="$2"; shift 2 ;;
        --outcome)         outcome="$2"; shift 2 ;;
        --tool-name)       tool_name="$2"; shift 2 ;;
        --args-summary)    args_summary="$2"; shift 2 ;;
        --error-kind)      error_kind="$2"; shift 2 ;;
        --correlation-id)  correlation_id="$2"; shift 2 ;;
        --parent-event-id) parent_event_id="$2"; shift 2 ;;
        --duration-ms)     duration_ms="$2"; shift 2 ;;
        --payload-json)    payload_json="$2"; shift 2 ;;
        *) echo "emit-event: unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Required fields
for var in run_id agent phase event_type; do
    if [[ -z "${!var}" ]]; then
        echo "emit-event: --${var//_/-} is required" >&2; exit 1
    fi
done

# Enum validation
case "$agent" in
    dev-lead|architect|coding|infrastructure|review|code-review|security-review|architecture-review|infrastructure-review|test-review) ;;
    *) echo "emit-event: invalid --agent: $agent" >&2; exit 1 ;;
esac
case "$event_type" in
    run_start|run_complete|phase_start|phase_complete|tool_call|gate_check|handoff_received|error) ;;
    *) echo "emit-event: invalid --event-type: $event_type" >&2; exit 1 ;;
esac
if [[ -n "$outcome" ]]; then
    case "$outcome" in success|fail|partial) ;; *) echo "emit-event: invalid --outcome: $outcome" >&2; exit 1 ;; esac
fi

# Per-event_type validation
case "$event_type" in
    run_complete|phase_complete|gate_check)
        [[ -z "$outcome" ]] && { echo "emit-event: $event_type requires --outcome" >&2; exit 1; } ;;
    tool_call)
        [[ -z "$tool_name" ]] && { echo "emit-event: tool_call requires --tool-name" >&2; exit 1; } ;;
    error)
        [[ -z "$error_kind" ]] && { echo "emit-event: error requires --error-kind" >&2; exit 1; } ;;
esac

# Truncate args_summary to 200 chars
if [[ -n "$args_summary" && ${#args_summary} -gt 200 ]]; then
    args_summary="${args_summary:0:200}"
fi

# JSON string escape: backslash, double-quote, control chars
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

# Timestamp: ISO 8601 UTC with millisecond precision
if date -u +%s.%3N >/dev/null 2>&1; then
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
else
    # macOS / BSD date — second precision fallback
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
fi

# Build JSON
parts=()
parts+=("\"timestamp\":\"$(json_escape "$timestamp")\"")
parts+=("\"run_id\":\"$(json_escape "$run_id")\"")
parts+=("\"agent\":\"$(json_escape "$agent")\"")
parts+=("\"phase\":\"$(json_escape "$phase")\"")
parts+=("\"event_type\":\"$(json_escape "$event_type")\"")
[[ -n "$correlation_id"  ]] && parts+=("\"correlation_id\":\"$(json_escape "$correlation_id")\"")
[[ -n "$parent_event_id" ]] && parts+=("\"parent_event_id\":\"$(json_escape "$parent_event_id")\"")
[[ -n "$outcome"         ]] && parts+=("\"outcome\":\"$(json_escape "$outcome")\"")
[[ -n "$duration_ms"     ]] && parts+=("\"duration_ms\":$duration_ms")
[[ -n "$tool_name"       ]] && parts+=("\"tool_name\":\"$(json_escape "$tool_name")\"")
[[ -n "$args_summary"    ]] && parts+=("\"args_summary\":\"$(json_escape "$args_summary")\"")
[[ -n "$error_kind"      ]] && parts+=("\"error_kind\":\"$(json_escape "$error_kind")\"")
[[ -n "$payload_json"    ]] && parts+=("\"payload\":$payload_json")

json="{"
for i in "${!parts[@]}"; do
    [[ $i -gt 0 ]] && json+=","
    json+="${parts[$i]}"
done
json+="}"

base_dir="${COPILOT_RUNS_DIR:-.copilot-runs}"
run_dir="$base_dir/$run_id"
mkdir -p "$run_dir"
printf '%s\n' "$json" >> "$run_dir/events.jsonl"
exit 0
