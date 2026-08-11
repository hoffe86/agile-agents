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

**That is the only exception, and it stays that way on purpose.** `scripts/check-vendored-drift.ps1`
compares each local copy with upstream and ignores exactly that line, so the check is meaningful
only while the list of exceptions stays at one — a growing set of "documented local edits" turns a
red result into noise people learn to skip. If a vendored skill needs improving, raise it upstream
and record it below; do not edit it here.

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
| playwright-generate-test | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/playwright-generate-test |
| pytest-coverage | `agile-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/pytest-coverage |
| refactor | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/refactor |
| ruff-recursive-fix | `agile-agents-python` | https://github.com/github/awesome-copilot/tree/main/skills/ruff-recursive-fix |
| security-review | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/security-review |
| terraform-azurerm-set-diff-analyzer | `agile-agents-terraform` | https://github.com/github/awesome-copilot/tree/main/skills/terraform-azurerm-set-diff-analyzer |
| threat-model-analyst | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/threat-model-analyst |
| update-avm-modules-in-bicep | `agile-agents-bicep` | https://github.com/github/awesome-copilot/tree/main/skills/update-avm-modules-in-bicep |
| webapp-testing | `agile-agents-core` | https://github.com/github/awesome-copilot/tree/main/skills/webapp-testing |

## Adopted — vendored once, no longer upstream

Skills that came from upstream but have since been **deleted there**. They are ours to maintain
now: `scripts/check-vendored-drift.ps1` deliberately does not track them (the URL 404s), and the
re-sync prompts below will not work.

| Skill | Plugin | Was | Status |
|---|---|---|---|
| polyglot-test-agent | `agile-agents-core` | `github/awesome-copilot/skills/polyglot-test-agent` | Removed upstream (confirmed 404, 2026-08). **Kept** — `testing` routes to it as the cross-language fallback when no language skill is installed, and `test-review` cites it for cross-language test scaffolding. Editing it in place is now allowed; it has no upstream to diverge from. |

Before removing an adopted skill, check what routes to it — a skill with no upstream is still a
dependency if an agent names it.

## Suggested upstream contributions

Improvements made locally to a vendored skill, then reverted to keep the copy byte-identical.
Recorded so the work is not lost and someone can raise it upstream instead.

| Skill | Improvement | Raised? |
|---|---|---|
| acquire-codebase-knowledge | `$SKILL_ROOT` was described as "the absolute path to the skill folder", which does not tell an agent how to obtain it. Clearer: "the directory of this `SKILL.md` — you know that absolute path, it is how you read this file." Added locally in `f992146`, reverted once the drift check surfaced it as an in-place edit. | not yet |

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
