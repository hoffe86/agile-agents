# Vendored Skills

These skills are unmodified copies from
[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/main/skills).
**Do not edit them in place** — extend via a wrapper skill in this same folder,
or contribute upstream.

## Skill → Upstream

| Skill | Upstream |
|---|---|
| acquire-codebase-knowledge | https://github.com/github/awesome-copilot/tree/main/skills/acquire-codebase-knowledge |
| add-educational-comments | https://github.com/github/awesome-copilot/tree/main/skills/add-educational-comments |
| aspire | https://github.com/github/awesome-copilot/tree/main/skills/aspire |
| breakdown-feature-implementation | https://github.com/github/awesome-copilot/tree/main/skills/breakdown-feature-implementation |
| breakdown-test | https://github.com/github/awesome-copilot/tree/main/skills/breakdown-test |
| codeql | https://github.com/github/awesome-copilot/tree/main/skills/codeql |
| conventional-commit | https://github.com/github/awesome-copilot/tree/main/skills/conventional-commit |
| create-github-action-workflow-specification | https://github.com/github/awesome-copilot/tree/main/skills/create-github-action-workflow-specification |
| create-implementation-plan | https://github.com/github/awesome-copilot/tree/main/skills/create-implementation-plan |
| csharp-docs | https://github.com/github/awesome-copilot/tree/main/skills/csharp-docs |
| dotnet-design-pattern-review | https://github.com/github/awesome-copilot/tree/main/skills/dotnet-design-pattern-review |
| editorconfig | https://github.com/github/awesome-copilot/tree/main/skills/editorconfig |
| ef-core | https://github.com/github/awesome-copilot/tree/main/skills/ef-core |
| git-commit | https://github.com/github/awesome-copilot/tree/main/skills/git-commit |
| import-infrastructure-as-code | https://github.com/github/awesome-copilot/tree/main/skills/import-infrastructure-as-code |
| multi-stage-dockerfile | https://github.com/github/awesome-copilot/tree/main/skills/multi-stage-dockerfile |
| polyglot-test-agent | https://github.com/github/awesome-copilot/tree/main/skills/polyglot-test-agent |
| pytest-coverage | https://github.com/github/awesome-copilot/tree/main/skills/pytest-coverage |
| refactor | https://github.com/github/awesome-copilot/tree/main/skills/refactor |
| refactor-method-complexity-reduce | https://github.com/github/awesome-copilot/tree/main/skills/refactor-method-complexity-reduce |
| ruff-recursive-fix | https://github.com/github/awesome-copilot/tree/main/skills/ruff-recursive-fix |
| security-review | https://github.com/github/awesome-copilot/tree/main/skills/security-review |
| terraform-azurerm-set-diff-analyzer | https://github.com/github/awesome-copilot/tree/main/skills/terraform-azurerm-set-diff-analyzer |
| threat-model-analyst | https://github.com/github/awesome-copilot/tree/main/skills/threat-model-analyst |
| update-avm-modules-in-bicep | https://github.com/github/awesome-copilot/tree/main/skills/update-avm-modules-in-bicep |
| webapp-testing | https://github.com/github/awesome-copilot/tree/main/skills/webapp-testing |

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
