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
| acquire-codebase-knowledge | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/acquire-codebase-knowledge |
| aspire | `agile-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/aspire |
| azure-deployment-preflight | `agile-agents-bicep` | https://github.com/github/awesome-copilot/tree/main/skills/azure-deployment-preflight |
| codeql | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/codeql |
| conventional-commit | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/conventional-commit |
| dotnet-design-pattern-review | `agile-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/dotnet-design-pattern-review |
| editorconfig | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/editorconfig |
| ef-core | `agile-agents-dotnet` | https://github.com/github/awesome-copilot/tree/main/skills/ef-core |
| git-commit | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/git-commit |
| import-infrastructure-as-code | `agile-agents-terraform` | https://github.com/github/awesome-copilot/tree/main/skills/import-infrastructure-as-code |
| multi-stage-dockerfile | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/multi-stage-dockerfile |
| polyglot-test-agent | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/polyglot-test-agent |
| playwright-generate-test | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/playwright-generate-test |
| pytest-coverage | `agile-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/pytest-coverage |
| refactor | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/refactor |
| ruff-recursive-fix | `agile-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/ruff-recursive-fix |
| security-review | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/security-review |
| terraform-azurerm-set-diff-analyzer | `agile-agents-terraform` | https://github.com/github/awesome-copilot/tree/main/skills/terraform-azurerm-set-diff-analyzer |
| threat-model-analyst | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/threat-model-analyst |
| update-avm-modules-in-bicep | `agile-agents-bicep` | https://github.com/github/awesome-copilot/tree/main/skills/update-avm-modules-in-bicep |
| webapp-testing | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/webapp-testing |

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
