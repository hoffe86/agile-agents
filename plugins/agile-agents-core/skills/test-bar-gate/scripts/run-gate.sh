#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Test-bar gate runner (bash).
#
# Runs the checks declared under `quality_gates.test_bar` in solution-profile.yaml,
# in order, fail-fast by default:
#
#   lint -> typecheck -> unit_test -> integration_test -> coverage -> mutation -> smoke
#
# A check runs when it is enabled AND resolves to a command. lint / typecheck /
# unit_test fall back to the per-stack palette in references/commands.yaml; the
# rest run only when the profile gives them an explicit command. The smoke slot
# comes from `testing.smoke` -- it starts the app, polls a URL, and always stops
# the process again.
#
# Emits gate_check events to $COPILOT_EVENT_LOG (or stdout) and prints a
# markdown failure report on the first failing check.
#
# Exit codes:
#   0 = all checks passed, or the gate was skipped
#   1 = at least one check failed
#   2 = fatal config error
#
# Usage:
#   ./run-gate.sh [--profile path/to/solution-profile.yaml] [--skill-root path]
#
# Requires `yq` (mikefarah, v4+) for YAML parsing. Install with:
#   brew install yq      # macOS
#   sudo snap install yq # Ubuntu
# -----------------------------------------------------------------------------
set -uo pipefail

PROFILE_PATH="./solution-profile.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SMOKE_COMMAND=""
SMOKE_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)       PROFILE_PATH="$2"; shift 2 ;;
    --skill-root)    SKILL_ROOT="$2";   shift 2 ;;
    --smoke-command) SMOKE_COMMAND="$2"; shift 2 ;;
    --smoke-url)     SMOKE_URL="$2";     shift 2 ;;
    -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

COMMANDS_YAML="${SKILL_ROOT}/references/commands.yaml"

if ! command -v yq >/dev/null 2>&1; then
  echo "ERROR: yq is required (https://github.com/mikefarah/yq)." >&2
  exit 2
fi
if [[ ! -f "$COMMANDS_YAML" ]]; then
  echo "ERROR: command palette not found: $COMMANDS_YAML" >&2
  exit 2
fi

# Checks in execution order. Only these three may fall back to the palette.
CHECK_ORDER=(lint typecheck unit_test integration_test coverage mutation)
PALETTE_BACKED=" lint typecheck unit_test "
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

# --- gate master switch ---
GATE_ENABLED="$(prof '.quality_gates.test_bar.enabled')"
if [[ "$GATE_ENABLED" == "false" ]]; then
  emit_event '{"event_type":"gate_check","check":"resolve","outcome":"skipped","reason":"disabled_by_profile"}'
  echo "test-bar-gate: disabled by profile - gate skipped."
  exit 0
fi

# --- stack resolution ---
# Maps a lint/build tool hint onto a palette key when the language name is not one.
alias_for_hint() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    *eslint*|*prettier*|*tsc*|*biome*) echo typescript ;;
    *ruff*|*black*|*mypy*|*pyright*)   echo python ;;
    *golangci*|*gofmt*)                echo go ;;
    *dotnet*)                          echo csharp ;;
    *) : ;;
  esac
}

declare -a CANDIDATES=()
while IFS= read -r s; do [[ -n "$s" ]] && CANDIDATES+=("$s"); done < <(
  if [[ -f "$PROFILE_PATH" ]]; then
    if [[ "$(yq -r '.quality_gates.test_bar.stacks | length' "$PROFILE_PATH" 2>/dev/null || echo 0)" -gt 0 ]]; then
      yq -r '.quality_gates.test_bar.stacks[]' "$PROFILE_PATH" 2>/dev/null
    else
      # primary_languages entries may be plain strings or { name: ... } maps.
      yq -r '(.tech_stack.primary_languages // [])[0] | (.name // .) // ""' "$PROFILE_PATH" 2>/dev/null
    fi
  fi | tr '[:upper:]' '[:lower:]'
)

declare -a STACKS=()
for cand in "${CANDIDATES[@]:-}"; do
  [[ -z "$cand" ]] && continue
  resolved=""
  if yq -e ".\"${cand}\"" "$COMMANDS_YAML" >/dev/null 2>&1; then
    resolved="$cand"
  else
    while IFS= read -r hint; do
      [[ -z "$hint" ]] && continue
      a="$(alias_for_hint "$hint")"
      if [[ -n "$a" ]] && yq -e ".\"${a}\"" "$COMMANDS_YAML" >/dev/null 2>&1; then resolved="$a"; break; fi
    done < <(argv_lines "$PROFILE_PATH" '.tech_stack.lint_format_tools'; argv_lines "$PROFILE_PATH" '.tech_stack.build_tools')
  fi
  if [[ -n "$resolved" ]]; then
    dup=""
    for s in "${STACKS[@]:-}"; do [[ "$s" == "$resolved" ]] && dup=1; done
    [[ -z "$dup" ]] && STACKS+=("$resolved")
  fi
done
# A profile-supplied command needs no stack, so an unmatched stack is not fatal
# on its own - we only skip when nothing at all resolved to a command.
[[ ${#STACKS[@]} -eq 0 ]] && STACKS=("")

FAIL_FAST="$(prof '.quality_gates.test_bar.fail_fast')"
[[ "$FAIL_FAST" == "false" ]] || FAIL_FAST="true"

failure_report() {
  local name="$1" stack="$2" cmdline="$3" code="$4" tail="$5" reason="${6-}"
  local shown="$stack"
  [[ -z "$shown" ]] && shown="(none - commands came from the profile)"
  printf '\n**Test-bar gate failed: %s**\n\n' "$name"
  printf -- '- **Stack detected:** %s\n' "$shown"
  printf -- '- **Command run:** `%s`\n' "$cmdline"
  printf -- '- **Exit code:** %s\n' "$code"
  [[ -n "$reason" ]] && printf -- '- **Reason:** %s\n' "$reason"
  printf -- '- **Working directory:** %s\n\n' "$(pwd)"
  printf '### stderr (last 30 lines)\n\n```text\n%s\n```\n\n' "$tail"
  printf '### Suggested next action\n\nReturn to `coding` (or `testing` if the failure belongs to the test layer) with this report and one corrective retry.\n'
}

run_check() {
  local name="$1" stack="$2"; shift 2
  local -a argv=("$@")
  local cmdline="${argv[*]}"

  echo "-> $name : $cmdline"
  if ! command -v "${argv[0]}" >/dev/null 2>&1; then
    # An uninstalled toolchain is the most common gate failure on a fresh
    # machine. Report it through the normal contract instead of dying.
    local msg="command not found: ${argv[0]}"
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"fail\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"exit_code\":127,\"stderr_tail\":$(json_str "$msg"),\"reason\":\"command_not_found\"}"
    failure_report "$name" "$stack" "$cmdline" 127 "$msg" "command_not_found"
    return 1
  fi

  local stderr_file; stderr_file="$(mktemp)"
  local start_ms; start_ms=$(($(date +%s%N)/1000000))
  "${argv[@]}" 2>"$stderr_file"
  local exit_code=$?
  local dur=$(( $(($(date +%s%N)/1000000)) - start_ms ))
  cat "$stderr_file" >&2

  if [[ $exit_code -eq 0 ]]; then
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"success\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"duration_ms\":${dur}}"
    rm -f "$stderr_file"
    return 0
  fi

  local tail_text; tail_text="$(tail -n 30 "$stderr_file" 2>/dev/null || true)"
  rm -f "$stderr_file"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"${name}\",\"outcome\":\"fail\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"exit_code\":${exit_code},\"stderr_tail\":$(json_str "$tail_text")}"
  failure_report "$name" "$stack" "$cmdline" "$exit_code" "$tail_text"
  return 1
}

# Opt-in "does the app come up?" slot. Always stops the process it started.
run_smoke() {
  local stack="$1"
  local -a argv=()
  local url=""
  # CLI overrides win: they carry the entry point the agent discovered when the
  # profile does not declare one (see references/startup-discovery.md).
  if [[ -n "$SMOKE_COMMAND" ]]; then
    read -r -a argv <<< "$SMOKE_COMMAND"
    url="$SMOKE_URL"
  else
    while IFS= read -r line; do [[ -n "$line" ]] && argv+=("$line"); done < <(argv_lines "$PROFILE_PATH" '.testing.smoke.command')
    url="$(prof '.testing.smoke.url')"
    [[ -z "$url" || "$url" == "null" ]] && url="$SMOKE_URL"
  fi
  if [[ ${#argv[@]} -eq 0 || -z "$url" || "$url" == "null" ]]; then
    # Not silently fine: a runnable project still has to be started. The script
    # cannot inspect a repo to work out how, so it reports that the caller must
    # resolve the entry point and re-invoke with --smoke-command / --smoke-url.
    emit_event '{"event_type":"gate_check","check":"smoke","outcome":"skipped","reason":"needs_discovery"}'
    echo "-> smoke : not configured — resolve the entry point (references/startup-discovery.md) and re-run with --smoke-command/--smoke-url, or record not_applicable/undetermined" >&2
    return 0
  fi
  local timeout; timeout="$(prof '.testing.smoke.timeout_s')"
  [[ -z "$timeout" || "$timeout" == "null" ]] && timeout=60

  local cmdline="${argv[*]}"
  echo "-> smoke : $cmdline (polling $url, timeout ${timeout}s)"
  if ! command -v "${argv[0]}" >/dev/null 2>&1; then
    local msg="command not found: ${argv[0]}"
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"fail\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"exit_code\":127,\"stderr_tail\":$(json_str "$msg"),\"reason\":\"command_not_found\"}"
    failure_report smoke "$stack" "$cmdline" 127 "$msg" "command_not_found"
    return 1
  fi

  local log_file; log_file="$(mktemp)"
  local start_ms; start_ms=$(($(date +%s%N)/1000000))
  "${argv[@]}" >"$log_file" 2>&1 &
  local pid=$!

  local up=0 reason="" deadline=$(( $(date +%s) + timeout ))
  while [[ $(date +%s) -lt $deadline ]]; do
    if ! kill -0 "$pid" 2>/dev/null; then reason="process exited early"; break; fi
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo 000)"
    if [[ "$code" =~ ^[0-9]+$ && "$code" -gt 0 && "$code" -lt 500 ]]; then up=1; break; fi
    sleep 2
  done
  local dur=$(( $(($(date +%s%N)/1000000)) - start_ms ))

  # A leaked listener holds the port and breaks the next run.
  if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; sleep 0.3; kill -9 "$pid" 2>/dev/null || true; fi
  wait "$pid" 2>/dev/null || true

  if [[ $up -eq 1 ]]; then
    emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"success\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"duration_ms\":${dur}}"
    rm -f "$log_file"
    return 0
  fi

  [[ -z "$reason" ]] && reason="no response within ${timeout}s"
  local tail_text; tail_text="$(tail -n 20 "$log_file" 2>/dev/null || true)"
  rm -f "$log_file"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"smoke\",\"outcome\":\"fail\",\"stack\":$(json_str "$stack"),\"command\":$(json_str "$cmdline"),\"exit_code\":1,\"stderr_tail\":$(json_str "$tail_text"),\"reason\":$(json_str "$reason")}"
  failure_report smoke "$stack" "$cmdline" 1 "$tail_text" "$reason"
  return 1
}

ALL_OK=0
RAN_ANYTHING=0
for stack in "${STACKS[@]}"; do
  for check in "${CHECK_ORDER[@]}"; do
    enabled_raw="$(prof ".quality_gates.test_bar.${check}.enabled")"
    if [[ -n "$enabled_raw" && "$enabled_raw" != "null" ]]; then
      [[ "$enabled_raw" == "true" ]] || continue
    else
      [[ "$DEFAULT_ENABLED" == *" $check "* ]] || continue
    fi

    declare -a argv=()
    while IFS= read -r line; do [[ -n "$line" ]] && argv+=("$line"); done \
      < <(argv_lines "$PROFILE_PATH" ".quality_gates.test_bar.${check}.command")
    if [[ ${#argv[@]} -eq 0 && -n "$stack" && "$PALETTE_BACKED" == *" $check "* ]]; then
      while IFS= read -r line; do [[ -n "$line" ]] && argv+=("$line"); done \
        < <(argv_lines "$COMMANDS_YAML" ".\"${stack}\".${check}")
    fi
    [[ ${#argv[@]} -eq 0 ]] && continue

    RAN_ANYTHING=1
    if ! run_check "$check" "$stack" "${argv[@]}"; then
      ALL_OK=1
      [[ "$FAIL_FAST" == "true" ]] && break 2
    fi
  done
done

if [[ $RAN_ANYTHING -eq 0 ]]; then
  emit_event '{"event_type":"gate_check","check":"resolve","outcome":"skipped","reason":"no_stack_match"}'
  echo "test-bar-gate: no stack match and no explicit commands - gate skipped." >&2
  exit 0
fi

if [[ $ALL_OK -eq 0 || "$FAIL_FAST" != "true" ]]; then
  run_smoke "${STACKS[0]}" || ALL_OK=1
fi

if [[ $ALL_OK -eq 0 ]]; then
  joined="$(printf '%s,' "${STACKS[@]}" | sed 's/,$//; s/^,//')"
  emit_event "{\"event_type\":\"gate_check\",\"check\":\"summary\",\"outcome\":\"success\",\"stack\":$(json_str "$joined")}"
  exit 0
fi
exit 1
