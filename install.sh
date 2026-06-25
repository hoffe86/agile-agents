#!/usr/bin/env bash
# Install or update the Copilot CLI development agent suite into a target repo
# or central user workspace.
#
# Usage:
#   install.sh --target <path> [--scope repo|user] [--mode install|update] [--dry-run] [--force]
#   install.sh --scope user                           # default target ~/.copilot
#   install.sh --help
#
# See INSTALL.md for the full workflow.

set -euo pipefail

# ── colors ────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_CYAN=$'\033[36m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_BOLD=''; C_OFF=''
fi

PRESERVE_FILES=("solution-profile.yaml")

TARGET=""
SCOPE="repo"
MODE="install"
DRY_RUN=0
FORCE=0

usage() {
    cat <<'EOF'
install.sh — copy the Copilot CLI agent suite into a target repo or user workspace.

OPTIONS
  --target <path>          Destination root (required for --scope repo).
  --scope <repo|user>      Default: repo. user defaults --target to ~/.copilot.
  --mode <install|update>  Default: install. update writes solution-profile.yaml.new
                           alongside an existing one (no clobber).
  --dry-run                Print the plan only.
  --force                  Allow overwriting preserve files in install mode.
  -h, --help               Show this help.

EXAMPLES
  Install into a target repo:
    ./install.sh --target ~/src/my-project
  Update existing install:
    ./install.sh --target ~/src/my-project --mode update
  Install user-scope skills (default ~/.copilot):
    ./install.sh --scope user
  Dry-run to preview:
    ./install.sh --target ~/src/my-project --dry-run
EOF
}

# ── arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)   TARGET="${2:-}"; shift 2 ;;
        --scope)    SCOPE="${2:-}";  shift 2 ;;
        --mode)     MODE="${2:-}";   shift 2 ;;
        --dry-run)  DRY_RUN=1; shift ;;
        --force)    FORCE=1;   shift ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "${C_RED}Unknown argument: $1${C_OFF}" >&2; usage; exit 2 ;;
    esac
done

case "$SCOPE" in repo|user) ;; *) echo "${C_RED}--scope must be repo or user${C_OFF}" >&2; exit 2 ;; esac
case "$MODE"  in install|update) ;; *) echo "${C_RED}--mode must be install or update${C_OFF}" >&2; exit 2 ;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$SCRIPT_DIR"
USER_SRC="$SCRIPT_DIR/user"
WORKFLOW_SRC="$SCRIPT_DIR/.github/workflows/agents-md-sync.yml"

if [[ "$SCOPE" == "repo" && ! -d "$REPO_SRC/agents" ]]; then
    echo "${C_RED}ERROR: source not found: $REPO_SRC/agents${C_OFF}" >&2; exit 1
fi
if [[ "$SCOPE" == "user" && ! -d "$USER_SRC" ]]; then
    echo "${C_RED}ERROR: source not found: $USER_SRC${C_OFF}" >&2; exit 1
fi

if [[ "$SCOPE" == "user" && -z "$TARGET" ]]; then
    TARGET="${HOME}/.copilot"
fi
if [[ -z "$TARGET" ]]; then
    echo "${C_RED}ERROR: --target is required for --scope repo${C_OFF}" >&2; exit 2
fi

if [[ ! -d "$TARGET" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "${C_YELLOW}NOTE: target does not exist (would be created): $TARGET${C_OFF}"
    else
        mkdir -p "$TARGET"
    fi
fi
TARGET="$(cd "$TARGET" && pwd)"

if [[ "$SCOPE" == "repo" && ! -d "$TARGET/.git" ]]; then
    echo "${C_YELLOW}WARNING: $TARGET is not a git repository${C_OFF}"
fi

# ── plan rows: ACTION|SRC|DST stored line-by-line ─────────────────────────────
PLAN=()

is_preserve() {
    local name="$1"
    for p in "${PRESERVE_FILES[@]}"; do [[ "$name" == "$p" ]] && return 0; done
    return 1
}

add_file() {
    local src="$1" dst="$2" preserve="${3:-0}" action="ADD"
    [[ -e "$src" ]] || return 0
    if [[ -e "$dst" ]]; then
        if [[ "$preserve" == "1" ]]; then
            if [[ "$MODE" == "update" ]]; then action="MERGE"
            elif [[ $FORCE -eq 1 ]];      then action="UPDATE"
            else                              action="PRESERVE"
            fi
        else
            action="UPDATE"
        fi
    fi
    PLAN+=("$action|$src|$dst")
}

add_dir() {
    local src_root="$1" dst_root="$2"
    [[ -d "$src_root" ]] || return 0
    while IFS= read -r -d '' f; do
        local rel="${f#$src_root/}"
        add_file "$f" "$dst_root/$rel" 0
    done < <(find "$src_root" -type f -print0)
}

# ── build plan ────────────────────────────────────────────────────────────────
if [[ "$SCOPE" == "repo" ]]; then
    AGENTS_DST="$TARGET/.github/agents"
    SKILLS_DST="$TARGET/.github/skills"
    WORKFLOW_DST="$TARGET/.github/workflows"

    if [[ -d "$REPO_SRC/agents" ]]; then
        for f in "$REPO_SRC/agents"/*.agent.md; do
            [[ -e "$f" ]] || continue
            add_file "$f" "$AGENTS_DST/$(basename "$f")" 0
        done
    fi

    if [[ -d "$REPO_SRC/skills" ]]; then
        for d in "$REPO_SRC/skills"/*/; do
            [[ -d "$d" ]] || continue
            add_dir "${d%/}" "$SKILLS_DST/$(basename "$d")"
        done
        for f in "$REPO_SRC/skills"/*; do
            [[ -f "$f" ]] || continue
            add_file "$f" "$SKILLS_DST/$(basename "$f")" 0
        done
    fi

    add_file "$REPO_SRC/AGENTS.md"             "$TARGET/AGENTS.md" 0
    add_file "$REPO_SRC/solution-profile.yaml" "$TARGET/solution-profile.yaml" 1
    add_file "$REPO_SRC/docs/AGENTS-MD-MAPPING.md" "$TARGET/.github/AGENTS-MD-MAPPING.md" 0
    add_dir  "$REPO_SRC/eval"    "$TARGET/eval"
    add_dir  "$REPO_SRC/scripts" "$TARGET/scripts"
    add_file "$WORKFLOW_SRC"     "$WORKFLOW_DST/agents-md-sync.yml" 0
else
    if [[ -d "$USER_SRC/skills" ]]; then
        for d in "$USER_SRC/skills"/*/; do
            [[ -d "$d" ]] || continue
            add_dir "${d%/}" "$TARGET/skills/$(basename "$d")"
        done
    fi
fi

if [[ ${#PLAN[@]} -eq 0 ]]; then
    echo "${C_YELLOW}Nothing to do (no source files found).${C_OFF}"; exit 0
fi

# ── enforce --force for preserve conflicts in install mode ────────────────────
if [[ "$MODE" == "install" && $FORCE -eq 0 && $DRY_RUN -eq 0 ]]; then
    conflicts=()
    for row in "${PLAN[@]}"; do
        IFS='|' read -r action _src dst <<<"$row"
        [[ "$action" == "PRESERVE" ]] && conflicts+=("$dst")
    done
    if [[ ${#conflicts[@]} -gt 0 ]]; then
        echo
        echo "${C_RED}PATH CONFLICT: the following preserve files already exist:${C_OFF}" >&2
        for c in "${conflicts[@]}"; do echo "  $c" >&2; done
        echo "${C_RED}Re-run with --force to overwrite, or use --mode update to write *.new alongside.${C_OFF}" >&2
        exit 3
    fi
fi

# ── execute ───────────────────────────────────────────────────────────────────
echo
echo "Scope:  $SCOPE"
echo "Mode:   $MODE$( [[ $DRY_RUN -eq 1 ]] && echo ' (dry-run)' )"
echo "Target: $TARGET"
echo

if [[ $DRY_RUN -eq 1 ]]; then
    printf '%-9s  %s\n' "ACTION" "DESTINATION"
    printf '%-9s  %s\n' "------" "-----------"
    sorted=$(printf '%s\n' "${PLAN[@]}" | sort)
    while IFS='|' read -r action _src dst; do
        printf '%-9s  %s\n' "$action" "$dst"
    done <<<"$sorted"
    echo
    echo "Total planned: ${#PLAN[@]} file(s)"
    exit 0
fi

added=0; updated=0; preserved=0; merged=0
for row in "${PLAN[@]}"; do
    IFS='|' read -r action src dst <<<"$row"
    case "$action" in
        PRESERVE)
            echo "${C_CYAN}  PRESERVE  $dst${C_OFF}"; preserved=$((preserved+1)) ;;
        MERGE)
            mkdir -p "$(dirname "$dst")"
            cp -f "$src" "$dst.new"
            echo "${C_CYAN}  MERGE     $dst.new  (review against existing)${C_OFF}"
            merged=$((merged+1)) ;;
        ADD)
            mkdir -p "$(dirname "$dst")"
            if ! cp -f "$src" "$dst"; then
                echo "${C_RED}ERROR copying $src -> $dst${C_OFF}" >&2; exit 1
            fi
            echo "${C_GREEN}  ADD       $dst${C_OFF}"; added=$((added+1)) ;;
        UPDATE)
            mkdir -p "$(dirname "$dst")"
            if ! cp -f "$src" "$dst"; then
                echo "${C_RED}ERROR copying $src -> $dst${C_OFF}" >&2; exit 1
            fi
            echo "${C_YELLOW}  UPDATE    $dst${C_OFF}"; updated=$((updated+1)) ;;
    esac
done

echo
echo "─── Summary ───────────────────────────────"
echo "${C_GREEN}  Added     : $added${C_OFF}"
echo "${C_YELLOW}  Updated   : $updated${C_OFF}"
echo "${C_CYAN}  Preserved : $preserved${C_OFF}"
echo "${C_CYAN}  Merge new : $merged${C_OFF}"
echo "  Total     : ${#PLAN[@]}"
echo

if [[ "$SCOPE" == "repo" ]]; then
    echo "Next steps:"
    echo "  1. Review/customise $TARGET/solution-profile.yaml"
    echo "  2. Run scripts/generate-agents-md.sh to (re)build AGENTS.md"
    if [[ $merged -gt 0 ]]; then
        echo "${C_YELLOW}  3. MERGE NEEDED: diff *.new files against the existing ones, then delete the *.new${C_OFF}"
    fi
else
    echo "User-scope skills installed to $TARGET/skills"
fi
