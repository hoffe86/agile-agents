#!/usr/bin/env bash
# Fail-closed scorer. Shared outcome contract prevents Bash/PowerShell drift.
# 0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup or judge error.
set -euo pipefail
# Use Git Bash's native path form even when literal semicolons inhibit conversion.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
if ! command -v python >/dev/null 2>&1; then
    echo '[judge] setup_error: python is required for the structured grading contract.' >&2
    echo '[judge-result] {"schema_version":2,"status":"setup_error","exit_code":4,"error_kind":"setup","reasons":["python is required"],"normalized_verdict":"SETUP_ERROR","score":0,"raw_response_persisted":false}'
    exit 4
fi
exec python -I -S -B -X utf8 "${SCRIPT_DIR}/../deepeval/score_workspace.py" "$@"
