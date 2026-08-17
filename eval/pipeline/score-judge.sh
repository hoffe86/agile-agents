#!/usr/bin/env bash
# score-judge.sh — default eval scorer (bash). LLM-as-judge: grade a produced
# workspace against a task's acceptance.md and exit 0=resolved / 2=partial / 1=failed
# (same contract as a per-task score.sh; the per-task override wins when present).
#
# Usage:
#   score-judge.sh <workspace> <acceptance.md>
#   score-judge.sh --self-test          # parser self-check, no copilot call
#
# Use a deterministic per-task score.sh instead when acceptance needs a real
# build/test rather than a judgement.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROMPT_TEMPLATE="${SCRIPT_DIR}/references/judge-prompt.md"

# Map a judge response (stdin) to an exit code. Last VERDICT line wins; anything
# unparseable is failed so an unclear judge never inflates the score.
verdict_exit() {
    local v
    v="$(grep -oiE 'VERDICT:[[:space:]]*(RESOLVED|PARTIAL|FAILED)' | tail -1 \
        | grep -oiE '(RESOLVED|PARTIAL|FAILED)' | tr '[:lower:]' '[:upper:]' || true)"
    case "$v" in
        RESOLVED) return 0 ;;
        PARTIAL)  return 2 ;;
        *)        return 1 ;;
    esac
}

if [[ "${1:-}" == "--self-test" ]]; then
    ok=1
    check() { local want="$1" txt="$2" got; set +e; printf '%s' "$txt" | verdict_exit; got=$?; set -e
        [[ "$got" == "$want" ]] || { echo "FAIL: want $want got $got for: ${txt//$'\n'/\\n}"; ok=0; }; }
    check 0 $'1. PASS - ok\nVERDICT: RESOLVED'
    check 2 $'VERDICT: PARTIAL\n'
    check 1 'VERDICT: FAILED'
    check 1 'no verdict here'
    check 1 $'VERDICT: RESOLVED\nVERDICT: FAILED'   # last wins
    check 0 'verdict: resolved'                     # case-insensitive
    [[ "$ok" == 1 ]] && { echo 'score-judge self-test: PASS'; exit 0; } || exit 1
fi

WS="${1:?workspace required}"
ACCEPTANCE="${2:?acceptance.md required}"

command -v copilot >/dev/null 2>&1 || { echo '[judge] copilot not on PATH — cannot score.'; exit 1; }
[[ -f "$ACCEPTANCE" ]] || { echo "[judge] missing acceptance: $ACCEPTANCE"; exit 1; }

# --- Collect produced artifacts (exclude seeded profile + .github) ---------------
MAX_PER_FILE=8000
MAX_TOTAL=60000
artifacts=""
total=0
if [[ -d "$WS" ]]; then
    while IFS= read -r f; do
        [[ $total -ge $MAX_TOTAL ]] && break
        rel="${f#"$WS"/}"
        body="$(cat "$f" 2>/dev/null || true)"
        [[ -z "$body" ]] && continue
        if [[ ${#body} -gt $MAX_PER_FILE ]]; then body="${body:0:$MAX_PER_FILE}"$'\n...[truncated]'; fi
        artifacts+="### ${rel}"$'\n```\n'"${body}"$'\n```\n\n'
        total=$(( total + ${#body} ))
    done < <(find "$WS" -type f -not -path '*/.github/*' -not -path '*/.git/*' -not -name 'solution-profile.yaml' -print | LC_ALL=C sort)
fi
if [[ -z "${artifacts// }" ]]; then
    echo '[judge] agent produced no gradable files → failed.'; exit 1
fi

# Fill the template. Use awk so acceptance/artifact contents are inserted literally
# (no sed metacharacter pitfalls).
acceptance_body="$(cat "$ACCEPTANCE")"
prompt="$(awk -v acc="$acceptance_body" -v art="$artifacts" '
    { gsub(/\{\{ACCEPTANCE\}\}/, acc); gsub(/\{\{ARTIFACTS\}\}/, art); print }
' "$PROMPT_TEMPLATE")"

resp="$(copilot -p "$prompt" -s --no-ask-user --allow-all-tools -C "$WS" 2>&1 || true)"
echo '[judge] ----- response -----'
echo "$resp"
echo '[judge] ----------------------'

set +e
printf '%s' "$resp" | verdict_exit
exit $?
