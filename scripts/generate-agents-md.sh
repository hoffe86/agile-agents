#!/usr/bin/env bash
# generate-agents-md.sh — bash equivalent of generate-agents-md.ps1
#
# Reads solution-profile.yaml + every .agent.md frontmatter and emits a
# vendor-neutral AGENTS.md (https://agents.md) so the repository is
# portable to Claude Code, Copilot CLI, Cursor, Aider, etc.
#
# Output is deterministic — agents and skills are sorted alphabetically and
# the timestamp is date-only UTC. YAML is read by a small awk parser; do not
# reintroduce a `yq` path — a second parser only ever drifts from this one.
#
# Usage:
#   scripts/generate-agents-md.sh [--profile PATH] [--agents-dir DIR]
#                                 [--skills-dir DIR] [--output PATH]
#                                 [--dry-run] [-h|--help]

set -euo pipefail

# ${#s} and ${s:0:n} count bytes under the C locale but characters under a UTF-8 one.
# The .ps1 counts characters (.NET strings), so without this the two generators truncate
# long descriptions at different points on any runner that leaves LANG unset. The sorts
# below stay pinned to LC_ALL=C per command and are unaffected.
export LC_ALL=C.UTF-8

usage() {
  sed -n '2,15p' "$0"
  exit 0
}

PROFILE_PATH=""
AGENTS_DIR=""
SKILLS_DIR=""
SKILLS_DIRS=()
OUTPUT=""
DRY_RUN=0

while (( "$#" )); do
  case "$1" in
    --profile)     PROFILE_PATH="$2"; shift 2 ;;
    --agents-dir)  AGENTS_DIR="$2";   shift 2 ;;
    --skills-dir)  SKILLS_DIR="$2";   shift 2 ;;
    --output)      OUTPUT="$2";       shift 2 ;;
    --dry-run)     DRY_RUN=1;         shift ;;
    -h|--help)     usage ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ── repo root ────────────────────────────────────────────────────────────────
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null || (cd "$script_dir/.." && pwd))"

resolve_first() {
  for p in "$@"; do [[ -n "$p" && -e "$p" ]] && { echo "$p"; return 0; }; done
  return 1
}

[[ -z "$PROFILE_PATH" ]] && PROFILE_PATH="$(resolve_first \
  "$repo_root/.github/solution-profile.yaml" \
  "$repo_root/solution-profile.yaml" || true)"
# Plugin agents win when present: that directory existing means we are in the marketplace repo,
# where the shipped suite is what AGENTS.md documents. .github/agents/ is checked second so a
# *consumer* repo still resolves -- and so a repo-local maintainer agent here (e.g. skill-scout)
# does not silently replace the whole roster in the generated file.
[[ -z "$AGENTS_DIR" ]] && AGENTS_DIR="$(resolve_first \
  "$repo_root/plugins/agile-agents-core/agents" \
  "$repo_root/.github/agents" \
  "$repo_root/agents" || true)"
if [[ -z "$SKILLS_DIR" ]]; then
  for d in "$repo_root"/plugins/agile-agents*/skills; do
    [[ -d "$d" ]] && SKILLS_DIRS+=("$d")
  done
  if (( ${#SKILLS_DIRS[@]} == 0 )); then
    d="$(resolve_first "$repo_root/.github/skills" "$repo_root/skills" || true)"
    [[ -n "$d" ]] && SKILLS_DIRS+=("$d")
  fi
else
  SKILLS_DIRS+=("$SKILLS_DIR")
fi
[[ -z "$OUTPUT" ]] && OUTPUT="$repo_root/AGENTS.md"

[[ -z "$PROFILE_PATH" ]] && { echo "solution-profile.yaml not found" >&2; exit 1; }
[[ -z "$AGENTS_DIR"   ]] && { echo "agents directory not found" >&2; exit 1; }

template_path="$script_dir/references/agents-md-template.md"
[[ -f "$template_path" ]] || { echo "template not found: $template_path" >&2; exit 1; }

# ── tiny YAML field reader (top-level section.key, scalars + simple lists) ──
# Strategy: locate "<section>:" line, then within that block (until next
# zero-indent key) find "  <key>:" and return the rhs (or list items).
yaml_scalar() {
  local section="$1" key="$2" file="$3"
  awk -v sec="$section" -v key="$key" '
    { sub(/\r$/, "") }
    BEGIN { in_sec=0 }
    /^[A-Za-z_][A-Za-z0-9_]*:/ {
      gsub(/:.*/, "", $0)
      in_sec = ($0 == sec) ? 1 : 0
      next
    }
    in_sec && /^[[:space:]]{2}[A-Za-z_][A-Za-z0-9_]*:/ {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      k = line; sub(/:.*/, "", k)
      v = line; sub(/^[^:]*:[[:space:]]*/, "", v)
      sub(/[[:space:]]+#.*$/, "", v)
      gsub(/^"|"$/, "", v); gsub(/^'\''|'\''$/, "", v)
      if (k == key) { print v; exit }
    }
  ' "$file"
}

yaml_list() {
  local section="$1" key="$2" file="$3"
  awk -v sec="$section" -v key="$key" '
    { sub(/\r$/, "") }
    BEGIN { in_sec=0; in_list=0 }
    /^[A-Za-z_][A-Za-z0-9_]*:/ {
      gsub(/:.*/, "", $0)
      in_sec = ($0 == sec) ? 1 : 0
      in_list = 0
      next
    }
    in_sec && /^[[:space:]]{2}[A-Za-z_][A-Za-z0-9_]*:/ {
      line = $0; sub(/^[[:space:]]+/, "", line)
      k = line; sub(/:.*/, "", k)
      v = line; sub(/^[^:]*:[[:space:]]*/, "", v)
      sub(/[[:space:]]+#.*$/, "", v)
      if (k == key) {
        in_list = 1
        if (v ~ /^\[.*\]$/) {
          gsub(/^\[|\]$/, "", v); n = split(v, arr, ",")
          for (i=1;i<=n;i++) { x=arr[i]; gsub(/^[[:space:]"'\'']+|[[:space:]"'\'']+$/,"",x); if(x!="") print x }
          in_list = 0
        }
      } else { in_list = 0 }
      next
    }
    in_sec && in_list && /^[[:space:]]+-[[:space:]]/ {
      v = $0; sub(/^[[:space:]]+-[[:space:]]*/, "", v)
      sub(/[[:space:]]+#.*$/, "", v)
      gsub(/^"|"$/, "", v); gsub(/^'\''|'\''$/, "", v)
      print v
    }
  ' "$file"
}

# Languages: each item may be a `{ name: x, version: y }` map.
format_languages() {
  local raw out="" item name ver
  raw="$(yaml_list tech_stack primary_languages "$PROFILE_PATH")"
  [[ -z "$raw" ]] && { echo "unspecified"; return; }
  while IFS= read -r item; do
    [[ -z "$item" ]] && continue
    if [[ "$item" == \{*\} ]]; then
      name="$(echo "$item" | sed -nE 's/.*name:[[:space:]]*"?([^",}]+)"?.*/\1/p')"
      ver="$(echo "$item" | sed -nE 's/.*version:[[:space:]]*"?([^",}]+)"?.*/\1/p')"
      [[ -n "$ver" ]] && item="${name}@${ver}" || item="$name"
    fi
    [[ -z "$out" ]] && out="$item" || out="$out, $item"
  done <<< "$raw"
  [[ -z "$out" ]] && echo "unspecified" || echo "$out"
}

scalar_or() { local v="$1" d="$2"; [[ -z "$v" ]] && echo "$d" || echo "$v"; }

# ── frontmatter reader for *.agent.md / SKILL.md ────────────────────────────
# Echoes "field|value" lines for: name, description, tools, agents.
# Lists (tools/agents) are emitted as "tools|a,b,c".
read_frontmatter() {
  local file="$1"
  awk '
    { sub(/\r$/, "") }
    BEGIN { in_fm=0; cur=""; buf="" }
    NR==1 && /^---[[:space:]]*$/ { in_fm=1; next }
    in_fm && /^---[[:space:]]*$/ { if (cur!="") print cur "|" buf; exit }
    in_fm {
      if (match($0, /^[A-Za-z_]+:[[:space:]]*>-?[[:space:]]*$/)) {
        if (cur!="") print cur "|" buf
        cur=$0; sub(/:.*/, "", cur); buf=""; next
      }
      if (match($0, /^[A-Za-z_]+:/)) {
        if (cur!="") print cur "|" buf
        key=$0; sub(/:.*/, "", key)
        val=$0; sub(/^[^:]*:[[:space:]]*/, "", val)
        if (val ~ /^\[.*\]$/) {
          gsub(/^\[|\]$/, "", val); gsub(/[[:space:]]*"|"[[:space:]]*/, "", val)
          gsub(/[[:space:]]*'\''[[:space:]]*/, "", val)
          print key "|" val
          cur=""; buf=""
        } else if (val == "") {
          cur=key; buf=""
        } else {
          gsub(/^"|"$/, "", val); gsub(/^'\''|'\''$/, "", val)
          print key "|" val
          cur=""; buf=""
        }
        next
      }
      if (cur != "") {
        line=$0; sub(/^[[:space:]]+/, "", line)
        if (buf=="") buf=line; else buf=buf " " line
      }
    }
  ' "$file"
}

fm_get() { local fm="$1" k="$2"; echo "$fm" | awk -F'|' -v k="$k" '$1==k {sub(/^[^|]*\|/,""); print; exit}'; }

# ── values ─────────────────────────────────────────────────────────────────
# Fall back to the git remote's repo name, not the checkout directory: CI clones into
# a folder named after the repo, developers clone into whatever they like.
repo_name_fallback="$(git -C "$repo_root" config --get remote.origin.url 2>/dev/null || true)"
repo_name_fallback="$(basename "${repo_name_fallback%/}" .git)"
[ -n "$repo_name_fallback" ] || repo_name_fallback="$(basename "$repo_root")"
project_name="$(scalar_or "$(yaml_scalar identity project_name "$PROFILE_PATH")" "$repo_name_fallback")"
default_branch="$(scalar_or "$(yaml_scalar identity default_branch "$PROFILE_PATH")" "main")"
doc_location="$(scalar_or "$(yaml_scalar documentation location "$PROFILE_PATH")" "unspecified")"
doc_platform="$(scalar_or "$(yaml_scalar documentation platform "$PROFILE_PATH")" "unspecified")"
backlog_platform="$(scalar_or "$(yaml_scalar backlog platform "$PROFILE_PATH")" "unspecified")"
branch_naming="$(scalar_or "$(yaml_scalar backlog branch_naming "$PROFILE_PATH")" "unspecified")"
commit_conv="$(scalar_or "$(yaml_scalar backlog commit_convention "$PROFILE_PATH")" "unspecified")"
languages="$(format_languages)"
generated_on="$(date -u +%Y-%m-%d)"

active_agents="$(yaml_list ai_copilot active_agents "$PROFILE_PATH" || true)"
mandatory_skills="$(yaml_list ai_copilot mandatory_skills "$PROFILE_PATH" | LC_ALL=C sort || true)"

is_active() {
  local name="$1"
  [[ -z "$active_agents" ]] && return 0
  echo "$active_agents" | grep -Fxq "$name"
}

# ── agents table ───────────────────────────────────────────────────────────
agents_table=""
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  fm="$(read_frontmatter "$f")"
  name="$(fm_get "$fm" name)"
  [[ -z "$name" ]] && continue
  is_active "$name" || continue
  desc="$(fm_get "$fm" description | tr -s ' ')"
  tools="$(fm_get "$fm" tools)"
  subs="$(fm_get "$fm" agents)"
  [[ -z "$tools" ]] && tools="_default_" || tools="$(echo "$tools" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | LC_ALL=C sort | paste -sd, - | sed 's/,/, /g')"
  [[ -z "$subs" ]]  && subs="_none_"   || subs="$(echo "$subs"  | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | LC_ALL=C sort | paste -sd, - | sed 's/,/, /g')"
  block="### \`$name\`"$'\n\n'"$desc"$'\n\n'"- **Tools**: $tools"$'\n'"- **Sub-agents**: $subs"$'\n'
  [[ -z "$agents_table" ]] && agents_table="$block" || agents_table="$agents_table"$'\n'"$block"
done < <(find "$AGENTS_DIR" -maxdepth 1 -name '*.agent.md' -type f | LC_ALL=C sort)
[[ -z "$agents_table" ]] && agents_table="_(no agents matched the active_agents filter)_"

# ── skills list ────────────────────────────────────────────────────────────
skills_list="_(skills directory not found)_"
if (( ${#SKILLS_DIRS[@]} > 0 )); then
  tmp=""
  for skills_root in "${SKILLS_DIRS[@]}"; do
    [[ -d "$skills_root" ]] || continue
    plugin="$(basename "$(dirname "$skills_root")")"
    while IFS= read -r d; do
      sm="$d/SKILL.md"
      [[ -f "$sm" ]] || continue
      fm="$(read_frontmatter "$sm")"
      name="$(fm_get "$fm" name)"; [[ -z "$name" ]] && continue
      desc="$(fm_get "$fm" description | tr -s ' ')"
      first="$(echo "$desc" | sed -E 's/([.!?])[[:space:]].*/\1/')"
      [[ ${#first} -gt 200 ]] && first="${first:0:197}..."
      line="- **$name** (\`$plugin\`) — $first"
      [[ -z "$tmp" ]] && tmp="$line" || tmp="$tmp"$'\n'"$line"
    done < <(find "$skills_root" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort)
  done
  [[ -n "$tmp" ]] && skills_list="$(echo "$tmp" | LC_ALL=C sort)"
fi

if [[ -n "$mandatory_skills" ]]; then
  mandatory_list="$(echo "$mandatory_skills" | sed 's/^/- `/;s/$/`/')"
else
  mandatory_list="_(none configured)_"
fi

if [[ -d "$repo_root/eval" ]]; then
  eval_pointer="see [\`./eval/\`](eval/)"
else
  eval_pointer="not configured (see plan H2)"
fi

# ── render ────────────────────────────────────────────────────────────────
rendered="$(awk '/^## Tokens[[:space:]]*$/{exit} {print}' "$template_path")"

# Values are passed as environment (assignments MUST precede `python3` — placing
# them after the script turns them into argv and every token renders empty).
if command -v python3 >/dev/null 2>&1; then
  rendered="$(printf '%s' "$rendered" | \
    PROJECT_NAME="$project_name" \
    GENERATED_ON="$generated_on" \
    LANGUAGES="$languages" \
    BACKLOG_PLATFORM="$backlog_platform" \
    DOC_LOCATION="$doc_location" \
    DOC_PLATFORM="$doc_platform" \
    BRANCH_NAMING="$branch_naming" \
    COMMIT_CONVENTION="$commit_conv" \
    DEFAULT_BRANCH="$default_branch" \
    ACTIVE_AGENTS_TABLE="$agents_table" \
    SKILLS_LIST="$skills_list" \
    MANDATORY_SKILLS_LIST="$mandatory_list" \
    EVAL_POINTER="$eval_pointer" \
    python3 -c '
import sys, os
text = sys.stdin.read()
for k in ("PROJECT_NAME","GENERATED_ON","LANGUAGES","BACKLOG_PLATFORM","DOC_LOCATION","DOC_PLATFORM","BRANCH_NAMING","COMMIT_CONVENTION","DEFAULT_BRANCH","ACTIVE_AGENTS_TABLE","SKILLS_LIST","MANDATORY_SKILLS_LIST","EVAL_POINTER"):
    text = text.replace("{{"+k+"}}", os.environ.get(k,""))
sys.stdout.write(text)
')"
else
  # Pure-bash fallback (slower).
  for pair in \
    "PROJECT_NAME|$project_name" \
    "GENERATED_ON|$generated_on" \
    "LANGUAGES|$languages" \
    "BACKLOG_PLATFORM|$backlog_platform" \
    "DOC_LOCATION|$doc_location" \
    "DOC_PLATFORM|$doc_platform" \
    "BRANCH_NAMING|$branch_naming" \
    "COMMIT_CONVENTION|$commit_conv" \
    "DEFAULT_BRANCH|$default_branch" \
    "ACTIVE_AGENTS_TABLE|$agents_table" \
    "SKILLS_LIST|$skills_list" \
    "MANDATORY_SKILLS_LIST|$mandatory_list" \
    "EVAL_POINTER|$eval_pointer" ; do
    k="${pair%%|*}"; v="${pair#*|}"
    rendered="${rendered//\{\{$k\}\}/$v}"
  done
fi

if (( DRY_RUN )); then
  printf '%s\n' "$rendered"
else
  printf '%s\n' "$rendered" > "$OUTPUT"
  echo "Wrote $OUTPUT"
fi
