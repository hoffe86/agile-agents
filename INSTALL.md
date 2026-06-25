# Installing the Copilot CLI agent suite

Two scripts ship the suite into a target project repo or your user workspace:

- `install.ps1` — Windows / PowerShell 5.1+
- `install.sh`  — Linux / macOS / WSL (bash)

Both wrap the same logic.

## Scopes

| Scope    | Target                   | What gets copied                                                                 |
| -------- | ------------------------ | -------------------------------------------------------------------------------- |
| `repo`   | A target project repo root | Agents flattened into `.github/agents/`, skills into `.github/skills/<name>/`, plus `AGENTS.md`, `solution-profile.yaml`, `eval/`, `scripts/`, `.github/AGENTS-MD-MAPPING.md`, and the `agents-md-sync.yml` workflow. |
| `user`   | `~/.copilot` by default  | The user-scope skills under `user/skills/` only.                                 |

The `coding/` and `backlog/` category folders do not exist in this repo — agents and skills are kept **flat** at `agents/` and `skills/`, as the Copilot CLI requires under `.github/agents/` and `.github/skills/`.

## Modes

- **install** (default) — write everything, but refuse to overwrite preserve files (`solution-profile.yaml`) without `--force`.
- **update** — overwrite all non-preserve files. For each preserve file, write the new version as `<name>.new` next to the existing one and print a `MERGE NEEDED` notice.

## Quick reference

```powershell
# Fresh install into a target repo
.\install.ps1 -TargetPath C:\src\my-project

# Pull a newer template version on top, keep your customised solution-profile.yaml
.\install.ps1 -TargetPath C:\src\my-project -Mode update

# Dry-run preview
.\install.ps1 -TargetPath C:\src\my-project -DryRun

# User-scope skills into ~/.copilot/skills/
.\install.ps1 -Scope user
```

```bash
./install.sh --target ~/src/my-project
./install.sh --target ~/src/my-project --mode update
./install.sh --target ~/src/my-project --dry-run
./install.sh --scope user
```

## The `solution-profile.yaml` merge workflow

`solution-profile.yaml` is the only file the script will not silently overwrite — it carries per-project customisations. In `--mode update` the new template is written as `solution-profile.yaml.new` so you can diff and merge:

```bash
diff -u solution-profile.yaml solution-profile.yaml.new
# bring in any new fields by hand, then:
rm solution-profile.yaml.new
```

After merging, regenerate `AGENTS.md`:

```powershell
.\scripts\generate-agents-md.ps1
```

## Exit codes

`0` success · `1` generic / I/O error · `2` invalid arguments · `3` preserve-file conflict (re-run with `--force` or `--mode update`).
