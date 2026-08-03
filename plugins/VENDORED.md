# Vendored Skills

These skills are unmodified copies from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills).
**Do not edit them in place** — extend via a wrapper skill in the same plugin,
or contribute upstream.

Vendored skills are spread across plugins — the **Plugin** column below is the
one to check before re-syncing.

**One sanctioned exception:** the `applies_to` frontmatter line. It is required on every
skill in this harness (see `.github/copilot-instructions.md` § Skill format) and upstream
has no equivalent field, so it is added locally and must be re-applied after any re-sync.
It is a one-line addition to frontmatter — nothing in the skill body is touched.

## Skill → Upstream

| Skill | Plugin | Upstream |
|---|---|---|
| acquire-codebase-knowledge | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/acquire-codebase-knowledge |
| aspire | `dev-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/aspire |
| breakdown-feature-implementation | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/breakdown-feature-implementation |
| breakdown-test | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/breakdown-test |
| codeql | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/codeql |
| conventional-commit | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/conventional-commit |
| create-github-action-workflow-specification | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/create-github-action-workflow-specification |
| create-implementation-plan | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/create-implementation-plan |
| dotnet-design-pattern-review | `dev-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/dotnet-design-pattern-review |
| editorconfig | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/editorconfig |
| ef-core | `dev-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/ef-core |
| git-commit | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/git-commit |
| import-infrastructure-as-code | `dev-agents-terraform` | https://github.com/github/awesome-copilot/tree/main/skills/import-infrastructure-as-code |
| multi-stage-dockerfile | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/multi-stage-dockerfile |
| polyglot-test-agent | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/polyglot-test-agent |
| pytest-coverage | `dev-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/pytest-coverage |
| refactor | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/refactor |
| refactor-method-complexity-reduce | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/refactor-method-complexity-reduce |
| ruff-recursive-fix | `dev-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/ruff-recursive-fix |
| security-review | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/security-review |
| terraform-azurerm-set-diff-analyzer | `dev-agents-terraform` | https://github.com/github/awesome-copilot/tree/main/skills/terraform-azurerm-set-diff-analyzer |
| threat-model-analyst | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/threat-model-analyst |
| update-avm-modules-in-bicep | `dev-agents-bicep` | https://github.com/github/awesome-copilot/tree/main/skills/update-avm-modules-in-bicep |
| webapp-testing | `dev-agents` | https://github.com/github/awesome-copilot/tree/main/skills/webapp-testing |

## Updating via Copilot CLI

Single skill:

> Update the `<skill-name>` vendored skill from upstream
> (https://github.com/github/awesome-copilot/tree/main/skills/<skill-name>)
> into this folder. Diff the changes and confirm before overwriting.

All vendored skills:

> Update all skills listed in `VENDORED.md` from upstream
> (github/awesome-copilot). Show a per-skill diff summary before overwriting.

## Hand-written vs vendored

Hand-written skills sit in this same folder without an entry in the table
above. To know which is which, check this file.

## Hand-written skills added since fork (Wave 1)

The following hand-written skills were added after the initial vendoring and
are **not** mirrored upstream — do not look for them in `github/awesome-copilot`:

- `code-localisation` — bounded symbol/file lookup before edits
- `run-event-log` — append-only structured trace of agent runs
- `test-bar-gate` — enforces the project's declared test-bar
- `e2e-testing` — Playwright/REST end-to-end test authoring
- `cost-budget` — per-run token & $ budgeting from `solution-profile.yaml`
