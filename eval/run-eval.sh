#!/usr/bin/env bash
# run-eval.sh — bash equivalent of run-eval.ps1
#
# Runs the dev-lead self-benchmark harness against one of two suites and
# captures per-task logs + a summary.json.
#
# NOTE: dev-lead invocation is currently a TODO (see Limitations in README.md).
# The script writes a placeholder log per task so the surrounding plumbing can
# be exercised end-to-end before the real CLI integration lands.
#
# Usage:
#   ./run-eval.sh --suite swe-bench-subset
#   ./run-eval.sh --suite custom-eval --task-filter 'task-03'
#   ./run-eval.sh --suite custom-eval --task-filter 'bicep|helm' --pass-threshold 75

set -euo pipefail

# --- Defaults ----------------------------------------------------------------
SUITE=""
TASK_FILTER=".*"
PASS_THRESHOLD=60
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_ROOT="${SCRIPT_DIR}/runs"

usage() {
    cat <<EOF
Usage: $0 --suite <swe-bench-subset|custom-eval> [options]

Options:
  --suite <name>             Required. Evaluation suite to run.
  --task-filter <regex>      Optional. Only run tasks whose ID matches. Default: .*
  --pass-threshold <int>     Optional. Resolved% needed to exit 0. Default: 60
  --output-root <path>       Optional. Where to write runs/. Default: ./runs
  -h, --help                 Show this help and exit.
EOF
}

# --- Parse args --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --suite)            SUITE="$2"; shift 2 ;;
        --task-filter)      TASK_FILTER="$2"; shift 2 ;;
        --pass-threshold)   PASS_THRESHOLD="$2"; shift 2 ;;
        --output-root)      OUTPUT_ROOT="$2"; shift 2 ;;
        -h|--help)          usage; exit 0 ;;
        *)                  echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [[ -z "$SUITE" ]]; then
    echo "ERROR: --suite is required" >&2; usage; exit 2
fi
if [[ "$SUITE" != "swe-bench-subset" && "$SUITE" != "custom-eval" ]]; then
    echo "ERROR: --suite must be swe-bench-subset or custom-eval" >&2; exit 2
fi

SUITE_ROOT="${SCRIPT_DIR}/${SUITE}"
[[ -d "$SUITE_ROOT" ]] || { echo "ERROR: missing suite folder $SUITE_ROOT" >&2; exit 2; }

# --- Resolve task list -------------------------------------------------------
TASK_IDS=()
TASK_REFS=()

if [[ "$SUITE" == "swe-bench-subset" ]]; then
    MANIFEST="${SUITE_ROOT}/tasks.json"
    [[ -f "$MANIFEST" ]] || { echo "ERROR: missing $MANIFEST" >&2; exit 2; }
    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: 'jq' is required for swe-bench-subset; install jq and re-run." >&2
        exit 2
    fi
    while IFS=$'\t' read -r id repo; do
        TASK_IDS+=("$id")
        TASK_REFS+=("hf://princeton-nlp/SWE-bench_Verified#${id}")
    done < <(jq -r '.[] | [.instance_id, .repo] | @tsv' "$MANIFEST")
else
    TASKS_DIR="${SUITE_ROOT}/tasks"
    [[ -d "$TASKS_DIR" ]] || { echo "ERROR: missing $TASKS_DIR" >&2; exit 2; }
    while IFS= read -r dir; do
        id="$(basename "$dir")"
        TASK_IDS+=("$id")
        TASK_REFS+=("${dir}/prompt.md")
    done < <(find "$TASKS_DIR" -mindepth 1 -maxdepth 1 -type d | sort)
fi

# --- Apply filter ------------------------------------------------------------
FILTERED_IDS=(); FILTERED_REFS=()
for i in "${!TASK_IDS[@]}"; do
    if [[ "${TASK_IDS[$i]}" =~ $TASK_FILTER ]]; then
        FILTERED_IDS+=("${TASK_IDS[$i]}")
        FILTERED_REFS+=("${TASK_REFS[$i]}")
    fi
done

if [[ ${#FILTERED_IDS[@]} -eq 0 ]]; then
    echo "ERROR: no tasks matched filter '$TASK_FILTER' in suite '$SUITE'." >&2
    exit 2
fi

# --- Set up run folder -------------------------------------------------------
RUN_ID="$(date +%Y%m%d-%H%M%S)-${SUITE}"
RUN_DIR="${OUTPUT_ROOT}/${RUN_ID}"
mkdir -p "$RUN_DIR"

echo "Run ID:    $RUN_ID"
echo "Suite:     $SUITE"
echo "Tasks:     ${#FILTERED_IDS[@]} (filter: '$TASK_FILTER')"
echo "Output:    $RUN_DIR"
echo ""

# --- Execute each task -------------------------------------------------------
RESOLVED=0; PARTIAL=0; FAILED=0
TASK_RESULTS_JSON=""

for i in "${!FILTERED_IDS[@]}"; do
    id="${FILTERED_IDS[$i]}"
    ref="${FILTERED_REFS[$i]}"
    log="${RUN_DIR}/${id}.log"

    printf "  → %s ... " "$id"

    # ========================================================================
    # TODO: invoke dev-lead via copilot CLI. Expected shape (subject to
    # confirmation once the non-interactive CLI contract is finalised):
    #
    #   copilot --agent dev-lead \
    #           --prompt-file "$ref" \
    #           --workspace  "$RUN_DIR" \
    #           --json-events \
    #     > "$log" 2>&1
    #
    # Until then we write a placeholder log so the harness plumbing is
    # exercisable end-to-end and the scoring code path is testable.
    # ========================================================================

    {
        echo "[$(date -Iseconds)] PLACEHOLDER RUN — dev-lead invocation not yet wired."
        echo "Suite:     $SUITE"
        echo "Task ID:   $id"
        echo "Prompt:    $ref"
        echo ""
        echo "When the CLI integration lands, this file will contain the full"
        echo "agent transcript plus the JSON event stream from H6."
    } > "$log"

    # Placeholder scoring — mark failed until real invocation lands so
    # baselines stay honest.
    status="failed"

    case "$status" in
        resolved) RESOLVED=$((RESOLVED+1)) ;;
        partial)  PARTIAL=$((PARTIAL+1)) ;;
        *)        FAILED=$((FAILED+1)) ;;
    esac

    TASK_RESULTS_JSON+="    {\"id\": \"${id}\", \"status\": \"${status}\"},"$'\n'
    echo "$status"
done

TOTAL=${#FILTERED_IDS[@]}
PCT=0
if [[ $TOTAL -gt 0 ]]; then
    PCT=$(awk "BEGIN { printf \"%.1f\", 100.0 * ${RESOLVED} / ${TOTAL} }")
fi
PARTIAL_PCT=$(awk "BEGIN { printf \"%.1f\", ($TOTAL>0) ? (100.0*${PARTIAL}/${TOTAL}) : 0 }")
FAILED_PCT=$(awk  "BEGIN { printf \"%.1f\", ($TOTAL>0) ? (100.0*${FAILED}/${TOTAL})  : 0 }")

# Strip trailing comma+newline from the JSON list
TASK_RESULTS_JSON="${TASK_RESULTS_JSON%,$'\n'}"

cat > "${RUN_DIR}/summary.json" <<EOF
{
  "suite": "${SUITE}",
  "run_id": "${RUN_ID}",
  "total": ${TOTAL},
  "resolved": ${RESOLVED},
  "partial": ${PARTIAL},
  "failed": ${FAILED},
  "resolved_pct": ${PCT},
  "partial_pct": ${PARTIAL_PCT},
  "failed_pct": ${FAILED_PCT},
  "tasks": [
${TASK_RESULTS_JSON}
  ]
}
EOF

echo ""
echo "Resolved: ${RESOLVED}/${TOTAL} (${PCT}%)"
echo "Partial:  ${PARTIAL}/${TOTAL}"
echo "Failed:   ${FAILED}/${TOTAL}"
echo "Summary:  ${RUN_DIR}/summary.json"

# --- Exit code ---------------------------------------------------------------
PASS=$(awk "BEGIN { print (${PCT} >= ${PASS_THRESHOLD}) ? 1 : 0 }")
if [[ "$PASS" == "1" ]]; then
    echo "PASS (>= ${PASS_THRESHOLD}%)"
    exit 0
else
    echo "FAIL (< ${PASS_THRESHOLD}%)"
    exit 1
fi
