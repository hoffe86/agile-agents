#!/usr/bin/env bash
# Python is a prelaunch prerequisite. No interpreter means no evaluation artifacts.
set -euo pipefail
# Git Bash's automatic path conversion skips paths containing semicolons.
# Its builtin pwd -W emits a native path; other Bash hosts use ordinary pwd.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
for interpreter in python python3; do
    if command -v "$interpreter" >/dev/null 2>&1; then
        exec "$interpreter" -I -S -B -X utf8 "${SCRIPT_DIR}/run_eval.py" "$@"
    fi
done
echo "ERROR: Python is required. Install Python and put its interpreter on PATH; no evaluation started." >&2
exit 2
