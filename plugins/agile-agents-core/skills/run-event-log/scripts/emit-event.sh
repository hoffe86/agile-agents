#!/usr/bin/env bash
# Append one structured JSON event to the current run's events.jsonl.
#
# Helper for the run-event-log skill. Validates supervisor-owned events and
# required fields per event_type,
# stamps timestamp = current UTC ISO 8601 with millisecond precision, and
# appends one JSON line to "${COPILOT_RUNS_DIR:-.copilot-runs}/<run-id>/events.jsonl".
# Append-only — never rewrites past events. See ../SKILL.md for full conventions.
#
# Usage:
#   ./emit-event.sh --run-id <uuid> --agent dev-lead --phase <name> --event-type <type> \
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
        *) echo "emit-event: unknown argument" >&2; exit 1 ;;
    esac
done

# Required fields
for var in run_id agent phase event_type; do
    if [[ -z "${!var}" ]]; then
        echo "emit-event: --${var//_/-} is required" >&2; exit 1
    fi
done

[[ "$agent" == "dev-lead" ]] || { echo "emit-event: only dev-lead may emit events" >&2; exit 1; }
[[ "$run_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
    || { echo "emit-event: --run-id must be a UUID" >&2; exit 1; }
[[ ${#phase} -le 64 ]] || { echo "emit-event: --phase must be 1-64 characters" >&2; exit 1; }
case "$event_type" in
    run_start|run_complete|phase_start|phase_complete|tool_call|gate_check|handoff_received|error) ;;
    *) echo "emit-event: invalid --event-type" >&2; exit 1 ;;
esac
if [[ -n "$outcome" ]]; then
    case "$outcome" in success|fail|partial) ;; *) echo "emit-event: invalid --outcome" >&2; exit 1 ;; esac
fi

# Per-event_type validation
case "$event_type" in
    run_complete|phase_complete|gate_check)
        [[ -z "$outcome" ]] && { echo "emit-event: $event_type requires --outcome" >&2; exit 1; } ;;
    run_start|phase_start)
        [[ -n "$outcome" ]] && { echo "emit-event: $event_type forbids --outcome" >&2; exit 1; } ;;
    tool_call)
        [[ -z "$tool_name" ]] && { echo "emit-event: tool_call requires --tool-name" >&2; exit 1; } ;;
    error)
        [[ -z "$error_kind" ]] && { echo "emit-event: error requires --error-kind" >&2; exit 1; } ;;
esac
if [[ -n "$duration_ms" && ! "$duration_ms" =~ ^(0|[1-9][0-9]*)$ ]]; then
    echo "emit-event: --duration-ms must be a non-negative integer" >&2; exit 1
fi

validate_payload() {
    local python_bin="${PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
        python_bin="$(command -v python3 || command -v python || true)"
    fi
    [[ -n "$python_bin" ]] || {
        echo "emit-event: Python is required to validate --payload-json" >&2
        return 1
    }
    "$python_bin" -c '
import json, sys
import math
import re
def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON property")
        value[key] = item
    return value
def reject_constant(value):
    raise ValueError("invalid JSON number")
def allowed(value, fields):
    if not isinstance(value, dict) or set(value) - set(fields):
        raise SystemExit("event contains unsupported object fields")
def safe(value):
    patterns = [
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization|accountkey|sharedaccesssignature|connection[_-]?string)\b\s*[:=]\s*\S+",
        r"\bbearer\s+[A-Z0-9._~+/=-]{8,}",
        r"\b(?:gh[pousr]_[A-Z0-9]{20,}|github_pat_[A-Z0-9_]{20,}|sk-[A-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[A-Z0-9_-]{30,}|xox[baprs]-[A-Z0-9-]{10,})\b",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:sig|signature)\s*=\s*[^&;\s]+",
        r"\b(?:https?|ftp)://[^/\s:@]+:[^/@\s]+@",
    ]
    if any(re.search(pattern, value, re.I) for pattern in patterns):
        return False
    phone = re.search(r"(?<!\w)\+?\d[\d .()-]{8,}\d(?!\w)", value)
    return not phone or sum(char.isdigit() for char in phone.group()) < 10
def scan(value):
    if isinstance(value, str):
        if not safe(value):
            raise SystemExit("event contains a string resembling a credential or personal identifier")
    elif isinstance(value, dict):
        for key, item in value.items():
            scan(key)
            scan(item)
    elif isinstance(value, list):
        for item in value:
            scan(item)
kind, outcome = sys.argv[2], sys.argv[3]
payload_text = sys.argv[1]
p = json.loads(payload_text, object_pairs_hook=unique_object, parse_constant=reject_constant) if payload_text else None
if payload_text and not isinstance(p, dict):
    raise SystemExit("payload must be a JSON object")
if kind == "run_start":
    allowed(p, {"requirement_summary", "profile_loaded"})
    if not isinstance(p.get("requirement_summary"), str) or not 1 <= len(p["requirement_summary"]) <= 200 or not isinstance(p.get("profile_loaded"), bool):
        raise SystemExit("run_start requires requirement_summary (1-200 characters) and profile_loaded (boolean)")
if kind == "gate_check":
    allowed(p, {"gate", "applicability", "reason"})
    if not isinstance(p.get("gate"), str) or not p["gate"]:
        raise SystemExit("gate_check requires payload.gate")
    if "applicability" in p and p["applicability"] != "not_applicable":
        raise SystemExit("gate_check applicability is unsupported")
    if "reason" in p and (not isinstance(p["reason"], str) or not p["reason"].strip()):
        raise SystemExit("gate_check reason must be a non-empty string")
    if p["gate"] == "test_bar" and outcome == "partial" and (p.get("applicability") != "not_applicable" or not isinstance(p.get("reason"), str) or not p["reason"].strip()):
        raise SystemExit("partial test_bar requires not_applicable applicability and a reason")
if kind == "handoff_received":
    allowed(p, {"from_agent", "sentinel"})
    workers = {"architect", "backlog-manager", "bootstrapper", "capability-scout", "coding", "data-scientist", "infrastructure", "review-lead", "code-reviewer", "security-reviewer", "architecture-reviewer", "infrastructure-reviewer", "test-reviewer", "data-reviewer"}
    if p.get("from_agent") not in workers or not isinstance(p.get("sentinel"), str) or not p["sentinel"].strip():
        raise SystemExit("handoff_received requires a worker payload.from_agent and non-empty sentinel")
if kind == "run_complete":
    allowed(p, {"cost_summary", "termination_reason"})
    if "termination_reason" in p and (not isinstance(p["termination_reason"], str) or not p["termination_reason"].strip()):
        raise SystemExit("run_complete termination_reason must be a non-empty string")
    if outcome in ("fail", "partial") and (not isinstance(p.get("termination_reason"), str) or not p["termination_reason"].strip()):
        raise SystemExit("non-success run_complete requires payload.termination_reason")
    summary = p.get("cost_summary")
    if not isinstance(summary, dict):
        raise SystemExit("run_complete requires payload.cost_summary")
    status = summary.get("status")
    if status in ("measured", "unmetered"):
        allowed(summary, {"status", "source", "usage"})
        usage = summary.get("usage")
        if summary.get("source") != "collect-usage.py" or not isinstance(usage, dict):
            raise SystemExit("measured cost_summary requires collect-usage.py source and usage object")
        required = {"session_id", "totals", "by_phase", "by_agent", "usd", "usd_basis", "unattributed", "warnings", "breaches"}
        if not required.issubset(usage) or not isinstance(usage["session_id"], str) or not usage["session_id"]:
            raise SystemExit("cost_summary usage is missing collector fields")
        if not isinstance(usage["by_phase"], dict) or not isinstance(usage["by_agent"], dict) or not isinstance(usage["warnings"], list) or not isinstance(usage["breaches"], list):
            raise SystemExit("cost_summary usage has invalid collector field types")
        def finite_nonnegative(value):
            if type(value) is int:
                return value >= 0
            if type(value) is float:
                return math.isfinite(value) and value >= 0
            return False
        def valid_metrics(m):
            integer_fields = {"calls", "tokens_in", "tokens_out", "tokens_reasoning", "tokens_cache_read", "tokens_total", "duration_ms"}
            allowed_fields = integer_fields | {"aiu", "models", "usd"}
            if not isinstance(m, dict) or set(m) != allowed_fields or any(type(m[k]) is not int or m[k] < 0 for k in integer_fields):
                return False
            if not finite_nonnegative(m.get("aiu")):
                return False
            if not isinstance(m.get("models"), list) or any(not isinstance(model, str) for model in m["models"]):
                return False
            usd_value = m.get("usd")
            return usd_value is None or finite_nonnegative(usd_value)
        allowed(usage, required)
        allowed(usage["totals"], {"calls", "tokens_in", "tokens_out", "tokens_reasoning", "tokens_cache_read", "tokens_total", "aiu", "duration_ms", "models", "usd"})
        allowed(usage["unattributed"], {"calls", "tokens_in", "tokens_out", "tokens_reasoning", "tokens_cache_read", "tokens_total", "aiu", "duration_ms", "models", "usd"})
        import math
        buckets = [usage["totals"], usage["unattributed"], *usage["by_phase"].values(), *usage["by_agent"].values()]
        if not all(valid_metrics(bucket) for bucket in buckets):
            raise SystemExit("cost_summary usage contains an invalid metric bucket")
        for diagnostic in [*usage["warnings"], *usage["breaches"]]:
            allowed(diagnostic, {"scope", "metric", "actual", "limit", "phase"})
            if (diagnostic.get("scope") not in {"per_run", "per_phase"} or
                    diagnostic.get("metric") not in {"tokens", "aiu", "usd"} or
                    not finite_nonnegative(diagnostic.get("actual")) or
                    not finite_nonnegative(diagnostic.get("limit")) or
                    ("phase" in diagnostic and not isinstance(diagnostic["phase"], str)) or
                    (diagnostic.get("scope") == "per_phase") != ("phase" in diagnostic)):
                raise SystemExit("cost_summary contains an invalid cap diagnostic")
        if not isinstance(usage.get("usd_basis"), str) or not usage["usd_basis"]:
            raise SystemExit("cost_summary usage requires usd_basis")
        if status == "measured" and (not finite_nonnegative(usage.get("usd")) or not usage["usd_basis"].startswith("rate:")):
            raise SystemExit("measured cost_summary requires rated numeric USD")
        if status == "unmetered" and (usage.get("usd") is not None or usage.get("usd_basis") != "not-metered"):
            raise SystemExit("unmetered cost_summary requires null USD and not-metered basis")
        if any((bucket["usd"] is None) == (status == "measured") for bucket in buckets):
            raise SystemExit("cost_summary metric USD values do not match status")
    elif status == "unavailable":
        allowed(summary, {"status", "source", "reason"})
        if summary.get("source") != "collect-usage.py" or not isinstance(summary.get("reason"), str) or not summary["reason"].strip():
            raise SystemExit("unavailable cost_summary requires source and reason")
    elif status == "disabled":
        allowed(summary, {"status", "reason"})
        if not isinstance(summary.get("reason"), str) or not summary["reason"].strip():
            raise SystemExit("disabled cost_summary requires a reason")
    else:
        raise SystemExit("cost_summary status must be measured, unmetered, unavailable, or disabled")
if kind == "error":
    allowed(p, {"message"})
    if not isinstance(p.get("message"), str) or not p["message"].strip() or len(p["message"]) > 200:
        raise SystemExit("error requires a short non-empty payload.message")
if kind in ("phase_start", "phase_complete", "tool_call") and p is not None:
    raise SystemExit("event type does not support a payload")
for value in sys.argv[4:]:
    if value and not safe(value):
        raise SystemExit("event contains a string resembling a credential or personal identifier")
scan(p)
' "$payload_json" "$event_type" "$outcome" "$phase" "$tool_name" "$args_summary" \
    "$error_kind" "$correlation_id" "$parent_event_id"
}

case "$event_type" in
    run_start|run_complete|gate_check|handoff_received|error)
        [[ -n "$payload_json" ]] || {
            echo "emit-event: $event_type requires --payload-json" >&2
            exit 1
        } ;;
esac
validate_payload || exit 1

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

# Timestamp: ISO 8601 UTC with millisecond precision; BSD date may return
# success while printing the unsupported %3N token literally.
timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
if [[ ! "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$ ]]; then
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
fi

# Build JSON
parts=()
parts+=("\"schema_version\":2")
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