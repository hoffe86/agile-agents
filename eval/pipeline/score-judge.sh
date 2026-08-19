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
#
# Build output is excluded deliberately. Without this, a compiled project buries the
# source: a task-01 run showed the judge 34 files of which 29 were bin/obj artifacts —
# including 8000 chars of raw binary from a .exe and a .pdb — which exhausted the
# budget before `tests/` was reached (it sorts last). The judge then reported "no
# OrderStatusEndpointTests shown", the prompt's "cannot verify ⇒ fail" rule turned that
# into a criterion failure, and a task whose tests actually passed 2/2 scored PARTIAL.
#
# The rule this encodes: never let the harness's own truncation masquerade as an agent
# defect. Anything dropped is reported to the judge explicitly (see OMITTED below).
MAX_PER_FILE=8000
MAX_TOTAL=60000
# Generated/vendored trees are pruned in the find below. Kept as explicit `-not -path`
# clauses rather than `-regextype posix-extended -regex`: the latter is a GNU extension
# and this script is documented as running on macOS, where BSD find would reject it.
artifacts=""
omitted=""
omitted_n=0
total=0
if [[ -d "$WS" ]]; then
    while IFS= read -r f; do
        rel="${f#"$WS"/}"
        # Binary files cost budget and tell the judge nothing. grep -I reports binaries
        # as non-matching, which is the cheapest portable text test available here.
        if ! grep -qI . "$f" 2>/dev/null; then continue; fi
        if [[ $total -ge $MAX_TOTAL ]]; then
            omitted_n=$(( omitted_n + 1 ))
            [[ $omitted_n -le 40 ]] && omitted+="- ${rel}"$'\n'
            continue
        fi
        body="$(cat "$f" 2>/dev/null || true)"
        [[ -z "$body" ]] && continue
        if [[ ${#body} -gt $MAX_PER_FILE ]]; then body="${body:0:$MAX_PER_FILE}"$'\n...[truncated]'; fi
        artifacts+="### ${rel}"$'\n```\n'"${body}"$'\n```\n\n'
        total=$(( total + ${#body} ))
    done < <(find "$WS" -type f \
                  -not -path '*/.github/*' -not -path '*/.git/*' \
                  -not -name 'solution-profile.yaml' \
                  -not -path '*/bin/*'        -not -path '*/obj/*' \
                  -not -path '*/node_modules/*' -not -path '*/vendor/*' \
                  -not -path '*/.venv/*'      -not -path '*/venv/*' \
                  -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' \
                  -not -path '*/.mypy_cache/*' -not -path '*/.gradle/*' \
                  -not -path '*/target/*'     -not -path '*/dist/*' \
                  -not -path '*/packages/*'   -not -path '*/.terraform/*' \
                  -not -path '*/.next/*' \
                  -print | LC_ALL=C sort)
fi

# Tell the judge what it could NOT see, so "absent" and "not shown" stay distinguishable.
if [[ $omitted_n -gt 0 ]]; then
    artifacts+=$'## Files omitted (artifact budget exhausted — NOT evidence of absence)\n\n'
    artifacts+="${omitted}"
    [[ $omitted_n -gt 40 ]] && artifacts+="- ...and $(( omitted_n - 40 )) more"$'\n'
    echo "[judge] WARNING: artifact budget exhausted; ${omitted_n} file(s) not shown to the judge." >&2
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

# An UNVERIFIED criterion means the harness could not show the judge the evidence. That
# is a harness limitation, not an agent result — say so loudly rather than letting it
# settle silently into the score.
if printf '%s' "$resp" | grep -qi 'UNVERIFIED'; then
    echo '[judge] WARNING: at least one criterion was UNVERIFIED (evidence omitted by the' >&2
    echo '[judge]          artifact budget). This score understates the agent — treat it as' >&2
    echo '[judge]          a harness limit and re-run with a larger MAX_TOTAL before citing it.' >&2
fi

set +e
printf '%s' "$resp" | verdict_exit
exit $?
