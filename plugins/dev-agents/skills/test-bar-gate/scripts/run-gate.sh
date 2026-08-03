#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Test-bar gate runner (bash).
#
# Runs lint -> typecheck -> test (fail-fast) for the stack detected from
# solution-profile.yaml. Emits gate_check events to $COPILOT_EVENT_LOG (or
# stdout) and prints a markdown failure report on the first non-zero exit.
#
# Exit codes:
#   0 = all checks passed (or gate skipped because no stack match)
#   1 = at least one check failed
#
# Usage:
#   ./run-gate.sh [--profile path/to/solution-profile.yaml] [--skill-root path]
#
# Requires `yq` (mikefarah, v4+) for YAML parsing. Install with:
#   brew install yq      # macOS
#   sudo snap install yq # Ubuntu
# If `yq` is missing the script exits non-zero with a clear message.
# -----------------------------------------------------------------------------
set -uo pipefail

PROFILE_PATH="./solution-profile.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)    PROFILE_PATH="$2"; shift 2 ;;
    --skill-root) SKILL_ROOT="$2";   shift 2 ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

COMMANDS_YAML="${SKILL_ROOT}/references/commands.yaml"

if ! command -v yq >/dev/null 2>&1; then
  echo "ERROR: yq is required (https://github.com/mikefarah/yq)." >&2
  exit 2
fi

emit_event() {
  local json="$1"
  if [[ -n "${COPILOT_EVENT_LOG:-}" ]]; then
    printf '%s\n' "$json" >> "$COPILOT_EVENT_LOG"
  else
    printf '%s\n' "$json"
  fi
}

# Resolve stack: solution-profile.tech_stack.primary_languages[0] (lowercased).
STACK=""
if [[ -f "$PROFILE_PATH" ]]; then
  STACK="$(yq -r '.tech_stack.primary_languages[0] // "" | downcase' "$PROFILE_PATH" 2>/dev/null || true)"
fi

if [[ -z "$STACK" ]] || ! yq -e ".${STACK}" "$COMMANDS_YAML" >/dev/null 2>&1; then
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"resolve\",\"outcome\":\"skipped\",\"reason\":\"no_stack_match\"}"
  echo "test-bar-gate: no stack match — gate skipped." >&2
  exit 0
fi

# Resolve fail_fast (default true).
FAIL_FAST="$(yq -r '.quality_gates.test_bar.fail_fast // true' "$PROFILE_PATH" 2>/dev/null || echo true)"

# For each check, prefer override at quality_gates.test_bar.commands.<check>,
# else default at <stack>.<check> in commands.yaml. Returns a JSON array string.
resolve_argv() {
  local check="$1"
  local override
  override="$(yq -o=json -I=0 ".quality_gates.test_bar.commands.${check} // \"\"" "$PROFILE_PATH" 2>/dev/null || echo '""')"
  if [[ "$override" != '""' && "$override" != "null" ]]; then
    printf '%s' "$override"
  else
    yq -o=json -I=0 ".${STACK}.${check}" "$COMMANDS_YAML"
  fi
}

# Convert JSON array of strings to a bash array (NUL-safe via @tsv would fail on
# embedded tabs; instead we read line-by-line which is safe for argv tokens).
json_to_argv() {
  local json="$1"
  local IFS=$'\n'
  read -r -d '' -a __out < <(printf '%s' "$json" | yq -r '.[]' && printf '\0')
  printf '%s\n' "${__out[@]}"
}

run_check() {
  local name="$1"
  local argv_json
  argv_json="$(resolve_argv "$name")"
  if [[ -z "$argv_json" || "$argv_json" == "null" ]]; then return 0; fi

  local -a argv=()
  while IFS= read -r line; do argv+=("$line"); done < <(json_to_argv "$argv_json")
  local cmdline="${argv[*]}"

  echo "→ $name : $cmdline"
  local stderr_file; stderr_file="$(mktemp)"
  local start_ms; start_ms=$(($(date +%s%N)/1000000))
  "${argv[@]}" 2> >(tee "$stderr_file" >&2)
  local exit_code=$?
  local end_ms; end_ms=$(($(date +%s%N)/1000000))
  local dur=$((end_ms - start_ms))

  if [[ $exit_code -eq 0 ]]; then
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"success\",\"stack\":\"${STACK}\",\"command\":$(printf '%s' "$cmdline" | yq -o=json -p=null '. // ""'),\"duration_ms\":${dur}}"
    rm -f "$stderr_file"
    return 0
  fi

  local tail; tail="$(tail -n 30 "$stderr_file" 2>/dev/null || true)"
  rm -f "$stderr_file"
  local tail_json; tail_json="$(printf '%s' "$tail" | yq -o=json -p=null '. // ""')"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"fail\",\"stack\":\"${STACK}\",\"command\":$(printf '%s' "$cmdline" | yq -o=json -p=null '. // ""'),\"exit_code\":${exit_code},\"stderr_tail\":${tail_json}}"

  cat <<EOF

❌ **Test-bar gate failed: ${name}**

- **Stack detected:** ${STACK}
- **Command run:** \`${cmdline}\`
- **Exit code:** ${exit_code}
- **Working directory:** $(pwd)

### stderr (last 30 lines)

\`\`\`text
${tail}
\`\`\`

### Suggested next action

Return to \`coding\` (or \`testing\` if the failure belongs to the test layer) with this report and one corrective retry.
EOF
  return 1
}

ALL_OK=0
for check in lint typecheck test; do
  if ! run_check "$check"; then
    ALL_OK=1
    if [[ "$FAIL_FAST" == "true" ]]; then break; fi
  fi
done

if [[ $ALL_OK -eq 0 ]]; then
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"summary\",\"outcome\":\"success\",\"stack\":\"${STACK}\"}"
  exit 0
fi
exit 1
