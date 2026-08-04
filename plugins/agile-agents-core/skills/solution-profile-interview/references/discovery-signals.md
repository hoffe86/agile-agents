# Discovery signals

Filesystem → profile-field map for step 2. **Read-only** — no builds, no installs, no
network. Field names below are the exact keys in `solution-profile.yaml`; if a signal is
absent, leave the field empty rather than guessing.

## identity

| Field | Signals |
|---|---|
| `project_name` | repo folder name, `*.sln`, `package.json:name`, `pyproject.toml:project.name`, `Cargo.toml:package.name`, `go.mod` module path |
| `repo_url` | `git remote get-url origin` |
| `default_branch` | `git symbolic-ref refs/remotes/origin/HEAD` |
| `owner` / `tech_lead` | `CODEOWNERS` top-level entry; `package.json:author`; `*.csproj` `<Authors>` |
| `lifecycle_stage` | **hint only** — tags `v1.0.0+` or `release/*` branches suggest `production`; no tags + no CI deploy suggests `poc`. Allowed values are `poc \| pilot \| production \| sunset`. Always confirm; this is a decision, not a fact. |

## documentation

| Field | Signals |
|---|---|
| `docs_root` | existing `docs/`, `documentation/`, `Documentation/`, or a path cross-referenced from `README.md` |
| `architecture_template` | `arc42*` filenames or arc42 section headings → `arc42`; only C4 diagrams → `c4-only` |
| `adr.location` | `docs/adr/`, `docs/decisions/`, `adr/` |
| `adr.format` | MADR front-matter (`status:`/`deciders:`) → `madr`; "Context / Decision / Consequences" headings → `nygard` |
| `diagram_convention` | `*.drawio` → `drawio`; `*.puml` → `plantuml`; ` ```mermaid ` fences with `C4Context` → `mermaid-c4` |

## backlog

| Field | Signals |
|---|---|
| `platform` | `git remote -v` host — github.com → `github-issues`; dev.azure.com / visualstudio.com → `ado-boards`; gitlab.com → `gitlab-issues`. Also `.azuredevops/` → `ado-boards` |
| `url` / `project` | the matching remote URL and its org/project path segments |
| `branch_naming` | most common prefix pattern across `git branch -a` |
| `commit_convention` | `git log --oneline -50` matching `^(feat\|fix\|chore\|docs\|refactor\|test)(\(.+\))?!?:` → `conventional-commits`; leading emoji → `gitmoji` |
| `required_commit_trailers` | recurring `Signed-off-by:` / `Co-authored-by:` in recent commits; `.github/PULL_REQUEST_TEMPLATE.md` |
| `pr_link_pattern` | `Closes #` / `AB#` occurrences in recent merge commits |

## tech_stack

| Field | Signals |
|---|---|
| `primary_languages` | source extensions + lockfiles: `*.sln`/`*.csproj` → csharp (version from `<TargetFramework>`); `pyproject.toml`/`requirements.txt` → python (`requires-python`); `package-lock.json`/`pnpm-lock.yaml` → js/ts; `go.mod` → go; `Cargo.toml` → rust; `pom.xml`/`build.gradle*` → java |
| `frameworks` | dependency manifests — `Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore`, `next`, `react`, `fastapi`, `django`, `gin-gonic/gin` |
| `package_managers` | lockfile present — `packages.lock.json` → nuget; `uv.lock` → uv; `poetry.lock` → poetry; `pnpm-lock.yaml` → pnpm |
| `test_frameworks` | `xunit`/`nunit`/`MSTest`/`TUnit` package refs; `pytest` in `pyproject.toml`; `jest`/`vitest` in `package.json` |
| `test_discipline` | `*.feature` files → `bdd`; test-file density ≈ source-file density → `tdd`; tests exist but sparse → `test-after`; otherwise **leave empty and ask** |
| `coverage_threshold` | `coverlet` / `--cov-fail-under` / `jest.config` `coverageThreshold` |
| `lint_format_tools` | `.editorconfig` + `dotnet-format`; `ruff.toml` / `[tool.ruff]`; `.eslintrc*`; `.pre-commit-config.yaml` |
| `build_tools` | `Makefile`, `Taskfile.yml`, `nx.json`, `*.sln`, `uv.lock` |

## infrastructure

| Field | Signals |
|---|---|
| `iac_tool` | `*.bicep` → `bicep`; `*.tf` → `terraform`; `*.json` ARM templates → `arm`; `Pulumi.yaml` → `pulumi` |
| `iac_root` | the directory containing the above (commonly `infra/`, `iac/`, `deploy/`) |
| `cloud` | azurerm/azapi providers or `*.bicep` → `azure`; `provider "aws"` → `aws`; `google` provider → `gcp` |
| `hosting_model` | `host.json` → `functions`; `Chart.yaml`/`kustomization.yaml`/`k8s/` → `aks`; `containerapp` resources → `aca`; `staticwebapp.config.json` → static web apps; `Dockerfile` alone is **not** conclusive |
| `environment_chain` | `*.bicepparam` / `*.tfvars` / overlay folder names (`dev`, `test`, `stage`, `prod`) |
| `secrets_store` | `Microsoft.KeyVault` resources → `key-vault`; `secrets.` refs in workflows → `github-secrets`; ADO variable groups → `ado-library` |
| `module_source` | `br/public:avm/` refs or `Azure/avm-*` registry modules → `avm` |
| `allowed_regions` | **do not infer** — a deployed region is not an allowed region. Ask. |

## cicd

| Field | Signals |
|---|---|
| `platform` | `.github/workflows/*.yml` → `github-actions`; `azure-pipelines*.yml` / `.azure-pipelines/` → `azure-pipelines`; `.gitlab-ci.yml` → `gitlab-ci`; `Jenkinsfile` → `jenkins` |
| `pipeline_paths` | the actual paths found above |
| `required_checks` | job/`name:` values in those workflows (confirm — branch protection is the real source and isn't in the repo) |
| `artifact_registry` | `*.azurecr.io` → `acr`; `ghcr.io` → `ghcr`; `nuget.org` push targets |
| `deployment_method` | `azure/login` with `client-id` + `permissions: id-token: write` → `oidc`; `creds:` secret → `service-principal` |
| `release_strategy` | branch topology — long-lived `develop` → `gitflow`; `release/*` → `release-branches`; only `main` + short branches → `trunk` |

## other

| Field | Signals |
|---|---|
| `team_communication.code_language` | language of `README.md` headings and top-of-file comments |
| `team_communication.review_policy.code_owners_required` | `CODEOWNERS` exists → likely `true`, but confirm (it's a branch-protection setting) |
| `legal.license` | `LICENSE` / `LICENSE.md` SPDX identifier |
| `quality_gates.test_bar.stacks` | leave empty — the gate auto-detects from `tech_stack.primary_languages` |
| `code_localisation.*` | leave at defaults (`backend: auto`) unless the user asks |

## Never infer

`compliance_security.data_classification`, `regulatory_scope`, `data_residency`,
`allowed_oss_licenses` (a *policy* denylist, not the repo's own `LICENSE`),
`operational.slo.*`, `cost_envelope.*`, `engagement_context.*`, `ai_copilot.*`.

These carry contractual or governance weight. A wrong value here is acted on by downstream
agents as if a human had approved it. Empty and asked beats populated and wrong.
