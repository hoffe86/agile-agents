#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Test-bar gate runner (bash).
#
# Runs the checks declared under `quality_gates.test_bar` in solution-profile.yaml,
# in order, fail-fast by default:
#
#   lint -> typecheck -> unit_test -> integration_test -> coverage -> mutation -> smoke
#
# Enabled checks require solution-declared commands; no language defaults.
# The smoke slot comes from `testing.smoke`: start, poll, always stop.
# Missing setup exits 2, never success. For a genuinely non-runnable project use
# --smoke-status not_applicable --smoke-detail "evidence inspected".
#
# Emits gate_check events to $COPILOT_EVENT_LOG (or stdout) and prints a
# markdown failure report on the first failing check.
#
# Exit codes:
#   0 = all checks passed, or the gate was skipped
#   1 = at least one check failed
#   2 = configuration gap (including unresolved smoke)
#
# Usage:
#   ./run-gate.sh [--profile path/to/solution-profile.yaml]
# Defaults to .github/solution-profile.yaml.
# An explicit path never falls back. Missing or invalid profiles exit 2.
#
# Requires `yq` (mikefarah, v4+) for YAML parsing. Install with:
#   brew install yq      # macOS
#   sudo snap install yq # Ubuntu
# -----------------------------------------------------------------------------
set -uo pipefail

PROFILE_PATH=""
SMOKE_COMMAND=""
SMOKE_URL=""
SMOKE_STATUS=""
SMOKE_DETAIL=""
SMOKE_PID=""
SMOKE_LOG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile|--smoke-command|--smoke-url|--smoke-status|--smoke-detail)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; } ;;
  esac
  case "$1" in
    --profile)       PROFILE_PATH="$2"; shift 2 ;;
    --smoke-command) SMOKE_COMMAND="$2"; shift 2 ;;
    --smoke-url)     SMOKE_URL="$2";     shift 2 ;;
    --smoke-status)  SMOKE_STATUS="$2";  shift 2 ;;
    --smoke-detail)  SMOKE_DETAIL="$2";  shift 2 ;;
    -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$PROFILE_PATH" ]]; then
  PROFILE_PATH="./.github/solution-profile.yaml"
fi
if [[ ! -f "$PROFILE_PATH" || ! -r "$PROFILE_PATH" ]]; then
  echo "ERROR: profile not found or unreadable: $PROFILE_PATH" >&2
  exit 2
fi
if ! command -v yq >/dev/null 2>&1; then
  echo "ERROR: yq is required (https://github.com/mikefarah/yq)." >&2
  exit 2
fi
if ! PROFILE_KIND="$(yq -r 'tag' "$PROFILE_PATH")" ||
   [[ "$PROFILE_KIND" != '!!map' ]]; then
  echo "ERROR: profile must be a YAML mapping: $PROFILE_PATH" >&2
  exit 2
fi
if [[ "$(yq -r 'length' "$PROFILE_PATH")" == 0 ]]; then
  echo "ERROR: profile must not be empty: $PROFILE_PATH" >&2
  exit 2
fi

# Checks in execution order.
CHECK_ORDER=(lint typecheck unit_test integration_test coverage mutation)
DEFAULT_ENABLED=" lint typecheck unit_test "

emit_event() {
  if [[ -n "${COPILOT_EVENT_LOG:-}" ]]; then
    printf '%s\n' "$1" >> "$COPILOT_EVENT_LOG"
  else
    printf '%s\n' "$1"
  fi
}

# JSON-encode an arbitrary string. `strenv` is used because yq has no raw-string
# input mode; passing via the environment avoids quoting/escaping pitfalls.
json_str() { __js="${1-}" yq -n -o=json 'strenv(__js)'; }

# Read a profile scalar; prints nothing when absent.
# Deliberately avoids yq's `//` operator: it treats `false` as absent, which
# would silently ignore every `enabled: false` in the profile.
prof() {
  [[ -f "$PROFILE_PATH" ]] || return 0
  local v
  v="$(yq -r "$1" "$PROFILE_PATH" 2>/dev/null || true)"
  [[ "$v" == "null" ]] && v=""
  printf '%s' "$v"
}

# A command may be a YAML list or a plain string. Emits one argv token per line.
argv_lines() {
  local file="$1" expr="$2" kind
  kind="$(yq -r "${expr} | tag" "$file" 2>/dev/null || echo '!!null')"
  case "$kind" in
    '!!seq') yq -r "${expr}[]" "$file" 2>/dev/null ;;
    '!!str') yq -r "${expr}" "$file" 2>/dev/null | tr -s '[:space:]' '\n' | sed '/^$/d' ;;
    *) : ;;
  esac
}

# Backticks below are literal Markdown, never command substitutions.
# shellcheck disable=SC2016
failure_report() {
  local name="$1" cmdline="$2" code="$3" tail="$4" reason="${5-}"
  printf '\n**Test-bar gate failed: %s**\n\n' "$name"
  printf -- '- **Command run:** `%s`\n' "$cmdline"
  printf -- '- **Exit code:** %s\n' "$code"
  [[ -n "$reason" ]] && printf -- '- **Reason:** %s\n' "$reason"
  printf -- '- **Working directory:** %s\n\n' "$(pwd)"
  printf '### stderr (last 30 lines)\n\n```text\n%s\n```\n\n' "$tail"
  printf '### Suggested next action\n\nReturn to `coding` (or `infrastructure` when the diff is IaC-only) with this report. Up to three corrective retries are allowed; if the gate still fails, halt and ask the user.\n'
}

configuration_gap() {
  local name="$1" detail="$2" reason="${3:-configuration_gap}"
  emit_event "{\"event_type\":\"gate_check\",\"check\":$(json_str "$name"),\"outcome\":\"fail\",\"reason\":$(json_str "$reason"),\"exit_code\":2,\"detail\":$(json_str "$detail")}"
  failure_report "$name" "" 2 "$detail" "$reason"
  return 2
}

# --- gate master switch ---
if [[ "$(yq -r '.quality_gates.test_bar | has("stacks")' "$PROFILE_PATH")" == "true" ]]; then
  configuration_gap resolve "quality_gates.test_bar.stacks is unsupported; declare check commands."
  exit 2
fi
GATE_ENABLED="$(prof '.quality_gates.test_bar.enabled')"
if [[ "$(yq -r '.quality_gates.test_bar.enabled | tag' "$PROFILE_PATH")" != '!!null' &&
      "$(yq -r '.quality_gates.test_bar.enabled | tag' "$PROFILE_PATH")" != '!!bool' ]]; then
  configuration_gap resolve "quality_gates.test_bar.enabled must be boolean."
  exit 2
fi
if [[ "$GATE_ENABLED" == "false" ]]; then
  emit_event '{"event_type":"gate_check","check":"resolve","outcome":"skipped","reason":"disabled_by_profile"}'
  echo "test-bar-gate: disabled by profile - gate skipped."
  exit 0
fi


FAIL_FAST="$(prof '.quality_gates.test_bar.fail_fast')"
if [[ "$(yq -r '.quality_gates.test_bar.fail_fast | tag' "$PROFILE_PATH")" != '!!null' &&
      "$(yq -r '.quality_gates.test_bar.fail_fast | tag' "$PROFILE_PATH")" != '!!bool' ]]; then
  configuration_gap resolve "quality_gates.test_bar.fail_fast must be boolean."
  exit 2
fi
[[ "$FAIL_FAST" == "false" ]] || FAIL_FAST="true"

# BSD date lacks %N. Seconds are sufficient for reporting; deadlines stay bounded.
now_ms() { printf '%s000' "$(date +%s)"; }

# A multiline shell program is not an argv item. Put it in a solution script.
valid_command() {
  local expr="$1" kind
  kind="$(yq -r "$expr | tag" "$PROFILE_PATH")"
  case "$kind" in
    '!!null'|'!!str') return 0 ;;
    '!!seq')
      [[ "$(yq -r "[${expr}[] | select(tag != \"!!str\" or test(\"[\\r\\n]\"))] | length" "$PROFILE_PATH")" == 0 ]] ;;
    *) return 1 ;;
  esac
}

run_check() {
  local name="$1"; shift
  local -a argv=("$@")
  local cmdline="${argv[*]}"

  echo "-> $name : $cmdline"
  if ! command -v "${argv[0]}" >/dev/null 2>&1; then
    # An uninstalled toolchain is the most common gate failure on a fresh
    # machine. Report it through the normal contract instead of dying.
    local msg="command not found: ${argv[0]}"
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"fail\",\"command\":$(json_str "$cmdline"),\"exit_code\":127,\"stderr_tail\":$(json_str "$msg"),\"reason\":\"command_not_found\"}"
    failure_report "$name" "$cmdline" 127 "$msg" "command_not_found"
    return 1
  fi

  local stderr_file; stderr_file="$(mktemp)"
  local start_ms; start_ms="$(now_ms)"
  "${argv[@]}" 2>"$stderr_file"
  local exit_code=$?
  local dur=$(( $(now_ms) - start_ms ))
  cat "$stderr_file" >&2

  if [[ $exit_code -eq 0 ]]; then
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"success\",\"command\":$(json_str "$cmdline"),\"duration_ms\":${dur}}"
    rm -f "$stderr_file"
    return 0
  fi

  local tail_text; tail_text="$(tail -n 30 "$stderr_file" 2>/dev/null || true)"
  rm -f "$stderr_file"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"fail\",\"command\":$(json_str "$cmdline"),\"exit_code\":${exit_code},\"stderr_tail\":$(json_str "$tail_text")}"
  failure_report "$name" "$cmdline" "$exit_code" "$tail_text"
  return 1
}

# Use a dedicated process group, including children when the entry point exits.
cleanup_smoke() {
  if [[ -n "$SMOKE_PID" ]]; then
    kill -TERM -- "-$SMOKE_PID" 2>/dev/null || true
    sleep 0.2
    kill -KILL -- "-$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
    SMOKE_PID=""
  fi
  [[ -z "$SMOKE_LOG" ]] || rm -f "$SMOKE_LOG"
  SMOKE_LOG=""
}
trap cleanup_smoke EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Runnable projects must start; absence of configuration is not non-applicability.
run_smoke() {
  local -a argv=()
  local url=""
  # CLI overrides win: they carry the entry point the agent discovered when the
  # profile does not declare one (see references/startup-discovery.md).
  if [[ -n "$SMOKE_COMMAND" ]]; then
    read -r -a argv <<< "$SMOKE_COMMAND"
    url="${SMOKE_URL:-$(prof '.testing.smoke.url')}"
  else
    if ! valid_command '.testing.smoke.command'; then
      configuration_gap smoke "testing.smoke.command must be a string or list of single-line strings."
      return 2
    fi
    while IFS= read -r line; do argv+=("$line"); done < <(argv_lines "$PROFILE_PATH" '.testing.smoke.command')
    url="${SMOKE_URL:-$(prof '.testing.smoke.url')}"
  fi
  if [[ -n "$SMOKE_STATUS" ]]; then
    if [[ -z "${SMOKE_DETAIL//[[:space:]]/}" || ( "$SMOKE_STATUS" != "not_applicable" && "$SMOKE_STATUS" != "undetermined" ) ]]; then
      configuration_gap smoke "Smoke status requires not_applicable/undetermined and nonblank evidence detail."
      return 2
    fi
    if [[ "$SMOKE_STATUS" == "undetermined" ]]; then
      configuration_gap smoke "$SMOKE_DETAIL" undetermined
      return 2
    fi
    if [[ ${#argv[@]} -gt 0 || -n "$url" ]]; then
      configuration_gap smoke "not_applicable conflicts with configured smoke command/URL."
      return 2
    fi
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"skipped\",\"reason\":\"not_applicable\",\"detail\":$(json_str "$SMOKE_DETAIL")}"
    return 0
  fi
  if [[ ${#argv[@]} -eq 0 || -z "${argv[0]//[[:space:]]/}" || -z "${url//[[:space:]]/}" ]]; then
    configuration_gap smoke "Resolve testing.smoke.command and url from solution evidence; or supply a not_applicable status with evidence." needs_discovery
    return 2
  fi
  local timeout; timeout="$(yq -r '.testing.smoke.timeout_s' "$PROFILE_PATH")"
  [[ "$(yq -r '.testing.smoke.timeout_s | tag' "$PROFILE_PATH")" == '!!null' ]] && timeout=60
  if [[ ! "$timeout" =~ ^[1-9][0-9]*$ ]]; then
    configuration_gap smoke "testing.smoke.timeout_s must be a positive integer."
    return 2
  fi
  if [[ ! "$url" =~ ^https?:// || ! $(command -v curl) ]]; then
    configuration_gap smoke "An HTTP(S) health URL and curl are required."
    return 2
  fi

  local cmdline="${argv[*]}"
  echo "-> smoke : $cmdline (polling $url, timeout ${timeout}s)"
  if ! command -v "${argv[0]}" >/dev/null 2>&1; then
    local msg="command not found: ${argv[0]}"
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"fail\",\"command\":$(json_str "$cmdline"),\"exit_code\":127,\"stderr_tail\":$(json_str "$msg"),\"reason\":\"command_not_found\"}"
    failure_report smoke "$cmdline" 127 "$msg" "command_not_found"
    return 1
  fi

  SMOKE_LOG="$(mktemp)"
  local start_ms; start_ms="$(now_ms)"
  set -m
  "${argv[@]}" >"$SMOKE_LOG" 2>&1 &
  SMOKE_PID=$!
  set +m

  local up=0 reason="" exit_code=1 deadline=$(( $(date +%s) + timeout ))
  while [[ $(date +%s) -lt $deadline ]]; do
    if ! kill -0 "$SMOKE_PID" 2>/dev/null; then break; fi
    local code remaining=$(( deadline - $(date +%s) ))
    [[ $remaining -gt 0 ]] || break
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$remaining" "$url" 2>/dev/null || true)"
    if [[ "$code" =~ ^[1-4][0-9][0-9]$ ]] && kill -0 "$SMOKE_PID" 2>/dev/null; then up=1; break; fi
    sleep 0.2
  done
  if [[ $up -eq 0 ]] && ! kill -0 "$SMOKE_PID" 2>/dev/null; then
    wait "$SMOKE_PID"
    exit_code=$?
    reason="process exited with $exit_code"
  fi
  local dur=$(( $(now_ms) - start_ms ))
  local tail_text; tail_text="$(tail -n 20 "$SMOKE_LOG" 2>/dev/null || true)"
  cleanup_smoke

  if [[ $up -eq 1 ]]; then
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"success\",\"command\":$(json_str "$cmdline"),\"duration_ms\":${dur}}"
    return 0
  fi

  [[ -z "$reason" ]] && reason="no response within ${timeout}s"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"fail\",\"command\":$(json_str "$cmdline"),\"exit_code\":$exit_code,\"stderr_tail\":$(json_str "$tail_text"),\"reason\":$(json_str "$reason")}"
  failure_report smoke "$cmdline" "$exit_code" "$tail_text" "$reason"
  return 1
}

ALL_OK=0
RAN_ANYTHING=0
for check in "${CHECK_ORDER[@]}"; do
    enabled_raw="$(prof ".quality_gates.test_bar.${check}.enabled")"
    enabled_kind="$(yq -r ".quality_gates.test_bar.${check}.enabled | tag" "$PROFILE_PATH")"
    if [[ "$enabled_kind" != '!!null' && "$enabled_kind" != '!!bool' ]]; then
      configuration_gap "$check" "quality_gates.test_bar.${check}.enabled must be boolean."
      ALL_OK=2
      [[ "$FAIL_FAST" == "true" ]] && break
      continue
    fi
    if [[ "$enabled_raw" == "false" || ( -z "$enabled_raw" && "$DEFAULT_ENABLED" != *" $check "* ) ]]; then
      reason="disabled_by_default"
      [[ "$enabled_raw" == "false" ]] && reason="disabled_by_profile"
      emit_event "{\"event_type\":\"gate_check\",\"check\":\"$check\",\"outcome\":\"skipped\",\"reason\":\"$reason\"}"
      continue
    fi

    declare -a argv=()
    if ! valid_command ".quality_gates.test_bar.${check}.command"; then
      configuration_gap "$check" "quality_gates.test_bar.${check}.command must be a string or list of single-line strings."
      ALL_OK=2
      [[ "$FAIL_FAST" == "true" ]] && break
      continue
    fi
    while IFS= read -r line; do argv+=("$line"); done \
      < <(argv_lines "$PROFILE_PATH" ".quality_gates.test_bar.${check}.command")
    if [[ ${#argv[@]} -eq 0 || -z "${argv[0]//[[:space:]]/}" ]]; then
      configuration_gap "$check" "Enabled check requires quality_gates.test_bar.${check}.command from existing solution CI/scripts; no language defaults."
      ALL_OK=2
      [[ "$FAIL_FAST" == "true" ]] && break
      continue
    fi

    RAN_ANYTHING=1
    if ! run_check "$check" "${argv[@]}"; then
      [[ $ALL_OK -eq 2 ]] || ALL_OK=1
      [[ "$FAIL_FAST" == "true" ]] && break
    fi
done

if [[ $ALL_OK -eq 0 || "$FAIL_FAST" != "true" ]]; then
  run_smoke
  smoke_exit=$?
  if [[ $smoke_exit -eq 2 ]]; then ALL_OK=2
  elif [[ $smoke_exit -ne 0 && $ALL_OK -ne 2 ]]; then ALL_OK=1; fi
fi

if [[ $ALL_OK -eq 0 ]]; then
  if [[ $RAN_ANYTHING -eq 0 && "$SMOKE_STATUS" == "not_applicable" ]]; then
    emit_event '{"event_type":"gate_check","check":"summary","outcome":"skipped","reason":"no_checks_enabled"}'
  else
    emit_event '{"event_type":"gate_check","check":"summary","outcome":"success"}'
  fi
  exit 0
fi
exit "$ALL_OK"
