#!/usr/bin/env bash
# run-eval.sh — bash equivalent of run-eval.ps1
#
# Runs the dev-lead self-benchmark harness against one of two suites and
# captures per-task logs + a summary.json.
#
# NOTE: Non-dry runs fail closed until a credential-free, network-disabled OS sandbox is
# available. Dry-run performs offline fixture preflight/staging. The mandatory human plan
# approval gate remains unchanged.
#
# Usage:
#   ./run-eval.sh --suite custom-eval --dry-run

set -euo pipefail

# --- Defaults ----------------------------------------------------------------
SUITE=""
TASK_FILTER=".*"
PASS_THRESHOLD=60
DRY_RUN=0
NO_ISOLATION=0
# Pinned rather than inherited: the CLI default comes from user config, which an isolated
# run does not have -- leaving it unset silently changed the model under test from
# claude-opus-4.8 to claude-sonnet-5 and made runs incomparable for reasons unrelated to
# isolation. A judge must also differ from the author: a model grading its own output is
# not an independent measurement.
AGENT_MODEL="${AGENT_MODEL:-claude-opus-4.8}"
JUDGE_MODEL="${JUDGE_MODEL:-gpt-5.6-sol}"
# Which default judge grades a task with no deterministic score.sh:
#   deepeval - intended to load acceptance-grading for verification. Live scoring is
#              currently disabled and returns UNVERIFIED without model/tool execution.
#   shell    - score-judge.sh: currently returns UNVERIFIED without model/tool execution.
#   both     - records matching UNVERIFIED outcomes while the safety hold is active.
# Default judges: 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup_error.
EVAL_SCORER="${EVAL_SCORER:-deepeval}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/plugins/agile-agents-core"
# Every plugin folder is registered, so companion skills (dotnet / python / bicep /
# terraform / trackers) resolve during a run — otherwise language tasks would silently
# fall back to repo conventions and the score wouldn't reflect the shipped suite.
PLUGIN_ARGS=()
for d in "${REPO_ROOT}"/plugins/agile-agents*; do
    [[ -d "$d" ]] && PLUGIN_ARGS+=(--plugin-dir "$d")
done
# Plugin-namespaced agent id — see run-eval.ps1 for the why. --plugin-dir loads
# this repo as plugin "agile-agents-core", so the supervisor is agile-agents-core:dev-lead.
DEV_LEAD_AGENT="agile-agents-core:dev-lead"
OUTPUT_ROOT="${SCRIPT_DIR}/runs"

usage() {
    cat <<EOF
Usage: $0 --suite <swe-bench-subset|custom-eval> [options]

Options:
  --suite <name>             Required. Evaluation suite to run.
  --task-filter <regex>      Optional. Only run tasks whose ID matches. Default: .*
  --pass-threshold <int>     Optional. Resolved% needed to exit 0. Default: 60
  --output-root <path>       Optional. Where to write runs/. Default: ./runs
  --agent-model <name>       Model the agent runs on. Default: claude-opus-4.8.
  --judge-model <name>       Model the judge runs on. Must differ from the agent model.
  --scorer <shell|deepeval|both>  Default judge. 'both' records agreement. Default: deepeval.
  --dry-run                  Preflight/stage fixtures and print commands; don't invoke CLI.
  --no-isolation             Use your own Copilot config instead of an isolated one.
                             Reinstates plugin shadowing: does NOT measure the working tree.
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
        --no-isolation)     NO_ISOLATION=1; shift ;;
        --agent-model)      AGENT_MODEL="$2"; shift 2 ;;
        --judge-model)      JUDGE_MODEL="$2"; shift 2 ;;
        --scorer)           EVAL_SCORER="$2"; shift 2 ;;
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
if [[ ! "$PASS_THRESHOLD" =~ ^[0-9]{1,3}$ ]] || (( 10#$PASS_THRESHOLD > 100 )); then
    echo "ERROR: --pass-threshold must be an integer from 0 through 100." >&2
    exit 2
fi
if [[ "$DRY_RUN" != "1" ]]; then
    echo "ERROR: live evaluation is disabled until an OS sandbox enforces credential-free, network-disabled access for both agent and judge processes. Use --dry-run for offline staging and preflight." >&2
    exit 2
fi

SUITE_ROOT="${SCRIPT_DIR}/${SUITE}"
[[ -d "$SUITE_ROOT" ]] || { echo "ERROR: missing suite folder $SUITE_ROOT" >&2; exit 2; }

if [[ "$DRY_RUN" != "1" && "$SUITE" != "custom-eval" ]] && ! command -v copilot >/dev/null 2>&1; then
    echo "ERROR: copilot CLI not found on PATH. Install it, run 'copilot login', or use --dry-run." >&2
    exit 2
fi

case "$EVAL_SCORER" in
    shell|deepeval|both) ;;
    *) echo "ERROR: --scorer must be shell, deepeval or both (got '$EVAL_SCORER')" >&2; exit 2 ;;
esac

if [[ "$AGENT_MODEL" == "$JUDGE_MODEL" ]]; then
    echo "ERROR: agent and judge models are both '$AGENT_MODEL'. A model grading its own output is not an independent measurement — set --judge-model to a different model." >&2
    exit 2
fi

# --- Isolated Copilot configuration root -------------------------------------
# Plugins install at **User** scope under the home directory, and `--plugin-dir` does
# NOT override an installed plugin of the same name — the installed copy wins silently.
# A run that believed it was exercising the working tree was reading whatever version
# happened to be installed (found at v0.14.0 against a working tree at v0.16.0). Every
# measurement of a modified existing skill was therefore of the wrong file.
#
# Redirecting HOME to a throwaway directory removes User-scope plugins from resolution,
# leaving --plugin-dir as the only source.
#
# Two consequences, both deliberate and both reported in the banner and summary.json:
#   1. Stored auth does not survive isolation, so a token must be supplied via the
#      environment. That is how CI supplies it anyway.
#   2. The user's own MCP servers are configured in the same place, so they are dropped.
#      Servers declared by the plugins themselves (plugins/agile-agents-core/.mcp.json ships
#      context7, microsoft-docs and playwright) still load, because they arrive via
#      --plugin-dir. That is the desired line: the harness keeps the tools it declares and
#      loses the ones that merely happened to be on the developer's machine. Verified —
#      task-04 depends on microsoft-docs for its primary-sources criterion and still scores
#      `resolved` under isolation.
ISOLATED_HOME=""

if [[ "$NO_ISOLATION" != "1" && "$DRY_RUN" != "1" && "$SUITE" != "custom-eval" ]]; then
    if [[ -z "${COPILOT_GITHUB_TOKEN:-}${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
        # Fail rather than fall back. A silent fall-back to the user's config would
        # produce a plausible-looking score for the wrong plugin version — exactly the
        # class of defect this isolation exists to remove.
        cat >&2 <<'EOF'
ERROR: isolated runs need a token in the environment, because stored auth does not
survive isolation. Set one of: COPILOT_GITHUB_TOKEN, GH_TOKEN, GITHUB_TOKEN.

  export GH_TOKEN="$(gh auth token)"

Or re-run with --no-isolation to use your own Copilot configuration — but be aware that
an installed plugin of the same name shadows --plugin-dir, so the run will NOT measure
the working tree.
EOF
        exit 2
    fi
fi

# Runs a command with the isolated configuration root in effect. Child processes (the
# judge runs as its own shell) inherit it, so the judge loads plugins exactly like the
# agent did — a judge with a different plugin set would grade against conventions the
# agent never saw.
run_isolated() {
    if [[ -n "$ISOLATED_HOME" ]]; then
        HOME="$ISOLATED_HOME" USERPROFILE="$ISOLATED_HOME" "$@"
    else
        "$@"
    fi
}

score_status() {
    local code="$1" result="${2:-}" acceptance="${3:-}"
    if [[ -n "$result" ]]; then
        python "${REPO_ROOT}/eval/grading.py" --result-status "$result" --exit-code "$code" --acceptance "$acceptance" || echo setup_error
    else
        case "$code" in
            0) echo resolved ;; 1) echo failed ;; 2) echo partial ;;
            3) echo unverified ;; *) echo setup_error ;;
        esac
    fi
}

# --- dev-lead invocation -----------------------------------------------------
# The repo is loaded as a local plugin (name "agile-agents-core") so `--agent
# agile-agents-core:dev-lead` resolves the in-repo agents/skills without `copilot plugin install`.
invoke_dev_lead() {
    local prompt_text="$1" workspace="$2" baseline="$3" log="$4"
    if [[ "$DRY_RUN" == "1" ]]; then
        {
            echo "[DRY RUN] would invoke dev-lead with:"
            echo "copilot -p <prompt> --agent $DEV_LEAD_AGENT ${PLUGIN_ARGS[*]} --allow-all-tools --no-ask-user --output-format json -C \"$workspace\" --add-dir \"$workspace\" --add-dir \"$baseline\""
        } > "$log"
        return 0
    fi
    run_isolated copilot -p "$prompt_text" \
        --agent "$DEV_LEAD_AGENT" \
        --model "$AGENT_MODEL" \
        "${PLUGIN_ARGS[@]}" \
        --allow-all-tools \
        --no-ask-user \
        --output-format json \
        -C "$workspace" \
        --add-dir "$workspace" \
        --add-dir "$baseline" \
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

if [[ "$NO_ISOLATION" != "1" && "$DRY_RUN" != "1" ]]; then
    ISOLATED_HOME="${RUN_DIR}/.copilot-home"
    mkdir -p "$ISOLATED_HOME"
fi

echo "Run ID:    $RUN_ID"
echo "Suite:     $SUITE"
echo "Models:    agent=$AGENT_MODEL  judge=$JUDGE_MODEL"
echo "Scorer:    $EVAL_SCORER"
echo "Tasks:     ${#FILTERED_IDS[@]} (filter: '$TASK_FILTER')"
echo "Output:    $RUN_DIR"
if [[ "$DRY_RUN" == "1" ]]; then
    echo "Config:    (dry run — the CLI is not invoked)"
elif [[ "$SUITE" == "custom-eval" ]]; then
    echo "Config:    noninteractive live evaluation is blocked by the mandatory human plan-approval gate"
elif [[ -n "$ISOLATED_HOME" ]]; then
    echo "Config:    isolated (${ISOLATED_HOME}) — plugins and MCP servers come only from --plugin-dir"
else
    echo "Config:    NOT ISOLATED — user plugins shadow --plugin-dir; this does not measure the working tree"
fi
echo ""

# Stage all selected fixtures before any agent invocation. The helper validates every
# profile and declared source/destination path before creating any task workspace.
if [[ "$SUITE" == "custom-eval" ]]; then
    command -v python >/dev/null 2>&1 || {
        echo "SETUP ERROR: python is required to preflight and stage custom-eval fixtures." >&2
        # No interpreter is available: serialize the known task ids with Bash
        # escaping rather than dropping the selected-suite denominator.
        rows=""
        for id in "${FILTERED_IDS[@]}"; do
            escaped="${id//\\/\\\\}"
            escaped="${escaped//\"/\\\"}"
            escaped="${escaped//$'\n'/\\n}"
            escaped="${escaped//$'\r'/\\r}"
            escaped="${escaped//$'\t'/\\t}"
            rows+="{\"id\":\"$escaped\",\"status\":\"setup_error\"},"
        done
        rows="${rows%,}"
        printf '{"suite":"custom-eval","run_id":"%s","run_status":"setup_error","total":%s,"setup_error_count":%s,"resolved":0,"partial":0,"failed":0,"unverified":0,"skipped":0,"blocked_approval_count":0,"dry_run":%s,"tasks":[%s],"setup_errors":["python is required"]}\n' \
            "$RUN_ID" "${#FILTERED_IDS[@]}" "${#FILTERED_IDS[@]}" "$([[ "$DRY_RUN" == 1 ]] && echo true || echo false)" "$rows" > "${RUN_DIR}/summary.json"
        exit 2
    }
    prepare_args=("${SUITE_ROOT}/prepare_inputs.py" --suite-root "$SUITE_ROOT" --run-dir "$RUN_DIR")
    for id in "${FILTERED_IDS[@]}"; do
        prepare_args+=(--task-id "$id")
    done
    prepare_status=0
    python "${prepare_args[@]}" > "${RUN_DIR}/preflight.json" || prepare_status=$?
    if [[ $prepare_status -ne 0 ]] || ! python -c '
import json,sys
p=json.load(open(sys.argv[1], encoding="utf-8"))
rows=p.get("tasks") if isinstance(p,dict) else None
valid=isinstance(rows,list) and all(isinstance(r,dict) and "task_id" in r and "status" in r for r in rows)
sys.exit(0 if valid and p.get("status")=="prepared" and sorted(r["task_id"] for r in rows)==sorted(sys.argv[2:]) else 1)
' "${RUN_DIR}/preflight.json" "${FILTERED_IDS[@]}"; then
        for id in "${FILTERED_IDS[@]}"; do
            printf '[setup_error] fixture preparation did not complete; no agent or judge was invoked.\n' > "${RUN_DIR}/${id}.log"
        done
        python -c '
import json,sys
try:
    preflight=json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError,ValueError):
    preflight={"errors":["preparation returned invalid JSON"]}
if not isinstance(preflight,dict):
    preflight={"errors":["preparation returned invalid schema"]}
rows=preflight.get("tasks",[])
originals={row["task_id"]:row["status"] for row in rows
           if isinstance(row,dict) and "task_id" in row and "status" in row} if isinstance(rows,list) else {}
tasks=[{"id": task_id, "status": "setup_error", "preparation_status": originals.get(task_id,"setup_error")}
       for task_id in sys.argv[5:]]
summary={"suite": "custom-eval", "run_id": sys.argv[2], "run_status": "setup_error",
         "total": len(tasks), "setup_error_count": sum(t["status"] == "setup_error" for t in tasks),
         "resolved": 0, "partial": 0, "failed": 0, "unverified": 0,
         "blocked_approval_count": 0, "skipped": 0,
         "dry_run": sys.argv[3] == "1", "tasks": tasks, "setup_errors": preflight.get("errors", [])}
with open(sys.argv[4], "w", encoding="utf-8") as output:
    json.dump(summary, output, indent=2)
    output.write("\n")
' "${RUN_DIR}/preflight.json" "$RUN_ID" "$DRY_RUN" "${RUN_DIR}/summary.json" "${FILTERED_IDS[@]}"
        echo "SETUP ERROR — no agent or judge was invoked. See ${RUN_DIR}/preflight.json."
        exit 2
    fi
    echo "Fixture preflight: passed; staged immutable baseline inputs outside each workspace."
fi

# The runner is noninteractive (`--no-ask-user`) while plan approval is mandatory.
# Do not infer approval or use a model response to pass this human-owned gate.
if [[ "$SUITE" == "custom-eval" && "$DRY_RUN" != "1" ]]; then
    python -c '
import json,sys
ids=sys.argv[1:-2]
run_id=sys.argv[-2]
output_path=sys.argv[-1]
summary={"suite":"custom-eval","run_id":run_id,"run_status":"blocked_approval",
         "blocking_gate":"human_plan_approval",
         "reason":"The noninteractive runner cannot receive the mandatory plan approval.",
         "total":len(ids),"blocked_approval_count":len(ids),"setup_error_count":0,
         "resolved":0,"partial":0,"failed":0,"unverified":0,"skipped":0,"dry_run":False,
         "tasks":[{"id":task_id,"status":"blocked_approval"} for task_id in ids]}
with open(output_path, "w", encoding="utf-8") as output:
    json.dump(summary, output, indent=2)
    output.write("\n")
' "${FILTERED_IDS[@]}" "$RUN_ID" "${RUN_DIR}/summary.json"
    for id in "${FILTERED_IDS[@]}"; do
        printf '[blocked_approval] mandatory human plan approval cannot be supplied by this noninteractive runner.\n' > "${RUN_DIR}/${id}.log"
    done
    echo "BLOCKED — custom-eval requires human plan approval; no agent or judge was invoked."
    echo "Summary:  ${RUN_DIR}/summary.json"
    exit 3
fi

# --- Execute each task -------------------------------------------------------
SCORER_ROWS=()
SCORER_AGREED=0
SCORER_TOTAL=0
RESOLVED=0; PARTIAL=0; FAILED=0; SKIPPED=0; UNVERIFIED=0; SETUP_ERROR=0
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
        # produces a prompt + workspace. Until then, report a setup error.
        {
            echo "SWE-bench task-prep not wired."
            echo "Task: $id  Ref: $ref"
            echo "Needs: dataset fetch + repo checkout at base commit before dev-lead can run."
        } > "$log"
        status="setup_error"
    else
        folder="$(dirname "$ref")"
        ws="${RUN_DIR}/ws/${id}"
        baseline="${RUN_DIR}/baseline/${id}"
        prompt_text="$(cat "$ref")"

        rc=0
        invoke_dev_lead "$prompt_text" "$ws" "$baseline" "$log" || rc=$?

        if [[ "$DRY_RUN" == "1" ]]; then
            # A dry run never invoked the agent, so there is nothing to grade. Marking
            # these "failed" (as this did) is a lie in the honest-looking direction: the
            # log reads "Failed: N/N" while the job exits 0 because the threshold was
            # set low, so a wiring check and a total collapse look identical.
            status="skipped"
        elif [[ $rc -ne 0 || ! -s "$log" ]]; then
            status="setup_error"
        elif [[ -f "${folder}/score.sh" ]]; then
            # Deterministic override: 0 resolved / 1 failed / 2 partial / 3 unverified;
            # other exits are setup errors.
            sc=0
            bash "${folder}/score.sh" "$ws" >> "$log" 2>&1 || sc=$?
            status="$(score_status "$sc")"
        else
            # Default: LLM judge grades the workspace against acceptance.md. Both judges run
            # under the same isolation — one loading a different plugin set than the agent
            # would grade against conventions the agent never saw.
            shell_status=""
            deep_status=""
            shell_result="${RUN_DIR}/${id}.shell.json"
            deep_result="${RUN_DIR}/${id}.deepeval.json"

            if [[ "$EVAL_SCORER" == "shell" || "$EVAL_SCORER" == "both" ]]; then
                sc=0
                JUDGE_MODEL="$JUDGE_MODEL" run_isolated bash "${SCRIPT_DIR}/score-judge.sh" "$ws" "${folder}/acceptance.md" --baseline-dir "$baseline" --result-json "$shell_result" >> "$log" 2>&1 || sc=$?
                shell_status="$(score_status "$sc" "$shell_result" "${folder}/acceptance.md")"
            fi

            if [[ "$EVAL_SCORER" == "deepeval" || "$EVAL_SCORER" == "both" ]]; then
                sc=0
                deep_args=("${REPO_ROOT}/eval/deepeval/score_workspace.py" "$ws" "${folder}/acceptance.md" --model "$JUDGE_MODEL"
                           --baseline-dir "$baseline" --result-json "$deep_result")
                # No run_isolated here: the scorer takes the isolated home as an argument and
                # sets it on the child itself, so the redirect cannot leak.
                [[ -n "$ISOLATED_HOME" ]] && deep_args+=(--isolated-home "$ISOLATED_HOME")
                python "${deep_args[@]}" >> "$log" 2>&1 || sc=$?
                deep_status="$(score_status "$sc" "$deep_result" "${folder}/acceptance.md")"
            fi

            if [[ "$EVAL_SCORER" == "both" ]]; then
                if [[ "$shell_status" == "$deep_status" ]]; then agree="true"; else agree="false"; fi
                echo "[scorer] shell=${shell_status} deepeval=${deep_status} agree=${agree}" >> "$log"
                echo "     [scorer] shell=${shell_status} deepeval=${deep_status} agree=${agree}"
                SCORER_ROWS+=("$(python -c '
import json,sys
print(json.dumps(dict(task=sys.argv[1],shell=sys.argv[2],deepeval=sys.argv[3],
                     agree=sys.argv[4]=="true",shell_result=sys.argv[5],deepeval_result=sys.argv[6])))
' "$id" "$shell_status" "$deep_status" "$agree" "$shell_result" "$deep_result")")
                [[ "$agree" == "true" ]] && SCORER_AGREED=$((SCORER_AGREED+1))
                SCORER_TOTAL=$((SCORER_TOTAL+1))
                # The shell judge stays authoritative while comparing, so a disagreement
                # cannot silently move the headline score during the evaluation itself.
                status="$shell_status"
            elif [[ "$EVAL_SCORER" == "deepeval" ]]; then
                status="$deep_status"
            else
                status="$shell_status"
            fi
        fi
    fi

    case "$status" in
        resolved) RESOLVED=$((RESOLVED+1)) ;;
        partial)  PARTIAL=$((PARTIAL+1)) ;;
        skipped)  SKIPPED=$((SKIPPED+1)) ;;
        failed)   FAILED=$((FAILED+1)) ;;
        unverified) UNVERIFIED=$((UNVERIFIED+1)) ;;
        *)        SETUP_ERROR=$((SETUP_ERROR+1)) ;;
    esac

    TASK_RESULTS_JSON+="$(python -c '
import json,sys
from pathlib import Path
root=Path(sys.argv[3])
grading={}
for scorer in ("shell","deepeval"):
    path=root / (sys.argv[1]+"."+scorer+".json")
    try:
        grading[scorer]=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        grading[scorer]=None
print(json.dumps(dict(id=sys.argv[1],status=sys.argv[2],grading=grading)))
' "$id" "$status" "$RUN_DIR"),"$'\n'
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
  "run_status": "$([[ "$DRY_RUN" == 1 ]] && echo skipped || { [[ "$SETUP_ERROR" -gt 0 ]] && echo setup_error || { [[ "$UNVERIFIED" -gt 0 ]] && echo unverified || echo scored; }; })",
  "total": ${TOTAL},
  "resolved": ${RESOLVED},
  "partial": ${PARTIAL},
  "failed": ${FAILED},
  "skipped": ${SKIPPED},
  "unverified": ${UNVERIFIED},
  "setup_error_count": ${SETUP_ERROR},
  "blocked_approval_count": 0,
  "dry_run": $([[ "$DRY_RUN" == "1" ]] && echo true || echo false),
  "scorer": "${EVAL_SCORER}",
  "live_run_status": $([[ "$SUITE" == "custom-eval" && "$DRY_RUN" == "1" ]] && echo '"blocked_approval: live runs also require the unavailable OS sandbox"' || echo null),
  "agent_model": "${AGENT_MODEL}",
  "judge_model": "${JUDGE_MODEL}",
  "isolated": $([[ -n "$ISOLATED_HOME" ]] && echo true || echo false),
  "mcp_servers": "$([[ -n "$ISOLATED_HOME" ]] && echo "plugin-declared only" || echo "plugin-declared + user config")",
  "resolved_pct": ${PCT},
  "partial_pct": ${PARTIAL_PCT},
  "failed_pct": ${FAILED_PCT},
  "scorer_comparison": [
$(IFS=$',\n'; echo "${SCORER_ROWS[*]}")
  ],
  "scorer_agreement_pct": $([[ $SCORER_TOTAL -gt 0 ]] && awk "BEGIN{printf \"%.1f\", 100*${SCORER_AGREED}/${SCORER_TOTAL}}" || echo null),
  "tasks": [
${TASK_RESULTS_JSON}
  ]
}
EOF

if [[ $SCORER_TOTAL -gt 0 ]]; then
    echo ""
    echo "Scorer agreement: ${SCORER_AGREED}/${SCORER_TOTAL} ($(awk "BEGIN{printf \"%.1f\", 100*${SCORER_AGREED}/${SCORER_TOTAL}}")%)"
    # Named individually: an aggregate agreement rate hides which task disagreed, and that
    # task is the whole reason to look.
    for row in "${SCORER_ROWS[@]}"; do
        [[ "$row" == *'"agree": false'* ]] && echo "  DISAGREE  ${row}"
    done
fi

echo ""
if [[ "$DRY_RUN" == "1" ]]; then
    # Wiring check only — say so plainly rather than reporting a score nobody computed.
    echo "DRY RUN — wiring validated for ${TOTAL} task(s); none executed, none scored."
    [[ "$SUITE" == "custom-eval" ]] && echo "Live run blocked: OS sandbox unavailable; mandatory plan approval also requires a human response."
    echo "Summary:  ${RUN_DIR}/summary.json"
    echo "Live scoring remains disabled until OS sandbox isolation and human plan approval are available."
    exit 0
fi

echo "Resolved: ${RESOLVED}/${TOTAL} (${PCT}%)"
echo "Partial:  ${PARTIAL}/${TOTAL}"
echo "Failed:   ${FAILED}/${TOTAL}"
echo "Unverified: ${UNVERIFIED}/${TOTAL}"
echo "Setup error: ${SETUP_ERROR}/${TOTAL}"
echo "Summary:  ${RUN_DIR}/summary.json"

# --- Exit code ---------------------------------------------------------------
[[ "$SETUP_ERROR" -gt 0 ]] && exit 2
[[ "$UNVERIFIED" -gt 0 ]] && exit 3
PASS=$(awk "BEGIN { print (${PCT} >= ${PASS_THRESHOLD}) ? 1 : 0 }")
if [[ "$PASS" == "1" ]]; then
    echo "PASS (>= ${PASS_THRESHOLD}%)"
    exit 0
else
    echo "FAIL (< ${PASS_THRESHOLD}%)"
    exit 1
fi
