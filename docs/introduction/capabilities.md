# Capabilities and limitations

This page separates what the harness does from what has been verified, so you can
decide how much to rely on it.

## What it does

- Profiles a repository and writes an approved solution profile
  ([bootstrap](../getting-started/bootstrap.md)).
- Verifies a requirement against prepared concepts and decision records, then
  decomposes it into independently implementable tasks with acceptance criteria.
- Optionally creates those tasks as linked child work items in Azure DevOps,
  GitHub Issues, Jira or Linear, through `backlog-manager` only.
- Implements approved tasks one at a time, with the author owning the tests.
- Runs the solution's configured deterministic checks before independent
  review: lint, type-check, unit tests, opt-in integration/coverage/mutation
  checks, then applicable smoke. Disabled checks are skips; an enabled check
  without a command is a configuration error, not a skip.
- Merges multi-lens independent review into one verdict with stable finding ids.
- Records run events and checks measured usage against the configured budget.
  A measured breach stops the run by default; explicit warn-only policy and
  unavailable telemetry are reported differently. See [budget checkpoints](../flow/budget.md).

## Deliberate boundaries

| Action | Who |
|---|---|
| Feature branch, commits, pushes | The task's author — never the default branch |
| Opening a pull request | Only with explicit, per-run user approval |
| Merging, closing, force-pushing, production deployment | Humans only, always |
| Non-production deployment | The project's own pipeline, only when `infrastructure.deploy_verify: dev` |

## Known limitations

- **Live end-to-end evaluation is blocked** at approval transport; full RPI runs
  are not continuously measured. See the [evaluation overview](../../eval/README.md).
- Tool grants are open (`tools: ["*"]`); they do not register absent MCP servers
  or authorize external services. Read-only roles are contracts, not technical denials.
- Model-tier metadata is advisory. Preferred models are configured manually in
  the native `/subagents` UI; profile order is not a runtime fallback guarantee.
- Optional technical depth comes from your solution or selected plugins. Without
  it, agents fall back to repository conventions and authoritative documentation
  and report that fallback.
