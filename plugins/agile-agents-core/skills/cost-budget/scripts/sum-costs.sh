#!/usr/bin/env bash
# sum-costs.sh — aggregate cost_usd / tokens from a run-event-log JSONL file.
#
# Usage:
#   sum-costs.sh <events.jsonl> [--threshold <usd>]
#
# Writes a JSON summary { total_usd, by_agent, by_phase } to stdout.
# Exits 2 if --threshold is set and total_usd exceeds it.
# Requires: jq.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <events.jsonl> [--threshold <usd>]" >&2
  exit 1
fi

EVENT_LOG="$1"; shift
THRESHOLD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --threshold) THRESHOLD="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$EVENT_LOG" ]]; then
  echo "event log not found: $EVENT_LOG" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

SUMMARY=$(jq -s '
  map(select(.cost_usd != null)) as $events
  | {
      total_usd: ([ $events[].cost_usd ] | add // 0 | . * 10000 | round / 10000),
      by_agent:  ($events | group_by(.agent // "unknown") | map({
          key:   (.[0].agent // "unknown"),
          value: { cost_usd:  ([.[].cost_usd] | add // 0),
                   tokens_in: ([.[].tokens_in // 0] | add),
                   tokens_out:([.[].tokens_out // 0] | add) }
      }) | from_entries),
      by_phase:  ($events | group_by(.phase // "unknown") | map({
          key:   (.[0].phase // "unknown"),
          value: { cost_usd:  ([.[].cost_usd] | add // 0),
                   tokens_in: ([.[].tokens_in // 0] | add),
                   tokens_out:([.[].tokens_out // 0] | add) }
      }) | from_entries)
    }
' "$EVENT_LOG")

echo "$SUMMARY"

if [[ -n "$THRESHOLD" ]]; then
  TOTAL=$(echo "$SUMMARY" | jq -r '.total_usd')
  if awk -v t="$TOTAL" -v th="$THRESHOLD" 'BEGIN { exit !(t+0 > th+0) }'; then
    echo "Cost $TOTAL USD exceeds threshold $THRESHOLD USD" >&2
    exit 2
  fi
fi
