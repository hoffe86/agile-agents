#!/usr/bin/env bash
# Compatibility entry point; the implementation and template ship with the skill.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$script_dir/../plugins/agile-agents-core/skills/solution-profile-interview/scripts/generate-agents-md.sh" "$@"
