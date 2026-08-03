#!/usr/bin/env bash
# run-eval.sh — bash equivalent of run-eval.ps1
#
# Runs the dev-lead self-benchmark harness against one of two suites and
# captures per-task logs + a summary.json.
#
# NOTE: custom-eval invokes dev-lead for real via `copilot --agent dev-agents:dev-lead
# --plugin-dir <repo>/plugins/dev-agents` (the plugin folder is loaded locally so the agent resolves
# without installing). swe-bench-subset task-prep (dataset fetch + repo checkout) is
# not yet wired; those tasks fail honestly until it lands.
#
# Usage:
#   ./run-eval.sh --suite swe-bench-subset
#   ./run-eval.sh --suite custom-eval --task-filter 'task-03'
#   ./run-eval.sh --suite custom-eval --task-filter 'bicep|helm' --pass-threshold 75
#   ./run-eval.sh --suite custom-eval --dry-run    # print commands, no auth/credits

set -euo pipefail

# --- Defaults ----------------------------------------------------------------
SUITE=""
TASK_FILTER=".*"
PASS_THRESHOLD=60
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/plugins/dev-agents"
# Every plugin folder is registered, so companion skills (dotnet / python / bicep /
# terraform / trackers) resolve during a run — otherwise language tasks would silently
# fall back to repo conventions and the score wouldn't reflect the shipped suite.
PLUGIN_ARGS=()
for d in "${REPO_ROOT}"/plugins/dev-agents*; do
    [[ -d "$d" ]] && PLUGIN_ARGS+=(--plugin-dir "$d")
done
# Plugin-namespaced agent id — see run-eval.ps1 for the why. --plugin-dir loads
# this repo as plugin "dev-agents", so the supervisor is dev-agents:dev-lead.
DEV_LEAD_AGENT="dev-agents:dev-lead"
OUTPUT_ROOT="${SCRIPT_DIR}/runs"

usage() {
    cat <<EOF
Usage: $0 --suite <swe-bench-subset|custom-eval> [options]

Options:
  --suite <name>             Required. Evaluation suite to run.
  --task-filter <regex>      Optional. Only run tasks whose ID matches. Default: .*
  --pass-threshold <int>     Optional. Resolved% needed to exit 0. Default: 60
  --output-root <path>       Optional. Where to write runs/. Default: ./runs
  --dry-run                  Print the resolved copilot command per task; don't execute.
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
        --dry-run)          DRY_RUN=1; shift ;;
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

if [[ "$DRY_RUN" != "1" ]] && ! command -v copilot >/dev/null 2>&1; then
    echo "ERROR: copilot CLI not found on PATH. Install it, run 'copilot login', or use --dry-run." >&2
    exit 2
fi

# --- dev-lead invocation -----------------------------------------------------
# The repo is loaded as a local plugin (name "dev-agents") so `--agent
# dev-agents:dev-lead` resolves the in-repo agents/skills without `copilot plugin install`.
invoke_dev_lead() {
    local prompt_text="$1" workspace="$2" log="$3"
    if [[ "$DRY_RUN" == "1" ]]; then
        {
            echo "[DRY RUN] would invoke dev-lead with:"
            echo "copilot -p <prompt> --agent $DEV_LEAD_AGENT ${PLUGIN_ARGS[*]} --allow-all-tools --no-ask-user --output-format json -C \"$workspace\" --add-dir \"$workspace\""
        } > "$log"
        return 0
    fi
    copilot -p "$prompt_text" \
        --agent "$DEV_LEAD_AGENT" \
        "${PLUGIN_ARGS[@]}" \
        --allow-all-tools \
        --no-ask-user \
        --output-format json \
        -C "$workspace" \
        --add-dir "$workspace" \
        > "$log" 2>&1
}

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

    if [[ "$SUITE" == "swe-bench-subset" ]]; then
        # ponytail: SWE-bench task-prep (fetch issue text from the HF dataset +
        # checkout the repo at the base commit + extract FAIL_TO_PASS) is a separate
        # integration, not yet wired. invoke_dev_lead is ready for it once prep
        # produces a prompt + workspace. Until then, fail honestly.
        {
            echo "SWE-bench task-prep not wired."
            echo "Task: $id  Ref: $ref"
            echo "Needs: dataset fetch + repo checkout at base commit before dev-lead can run."
        } > "$log"
        status="failed"
    else
        folder="$(dirname "$ref")"
        ws="${RUN_DIR}/ws/${id}"
        mkdir -p "${ws}/.github"
        if [[ -f "${folder}/solution-profile.yaml" ]]; then
            cp "${folder}/solution-profile.yaml" "${ws}/solution-profile.yaml"
            cp "${folder}/solution-profile.yaml" "${ws}/.github/solution-profile.yaml"
        fi
        prompt_text="$(cat "$ref")"

        rc=0
        invoke_dev_lead "$prompt_text" "$ws" "$log" || rc=$?

        if [[ "$DRY_RUN" == "1" ]]; then
            status="failed"          # not a real run; excluded from a real score
        elif [[ $rc -ne 0 || ! -s "$log" ]]; then
            status="failed"
        elif [[ -f "${folder}/score.sh" ]]; then
            # Per-task deterministic override: exit 0 = resolved, 2 = partial, else failed.
            sc=0
            bash "${folder}/score.sh" "$ws" >> "$log" 2>&1 || sc=$?
            case "$sc" in 0) status="resolved" ;; 2) status="partial" ;; *) status="failed" ;; esac
        else
            # Default: LLM judge grades the workspace against acceptance.md.
            sc=0
            bash "${SCRIPT_DIR}/score-judge.sh" "$ws" "${folder}/acceptance.md" >> "$log" 2>&1 || sc=$?
            case "$sc" in 0) status="resolved" ;; 2) status="partial" ;; *) status="failed" ;; esac
        fi
    fi

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
