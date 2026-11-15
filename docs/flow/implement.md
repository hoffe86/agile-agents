# Implement and quality gates

## One task at a time

Approved tasks run sequentially in dependency order. For each application or IaC
task, `dev-lead` either authors it directly — including its tests — or delegates
to `coding` or `infrastructure`. Analysis, modelling and evaluation always go to
`data-scientist`.

The author owns the tests. Every behaviour added or modified must name the test
that asserts it, and every change to an existing test must explain why the old
assertion was invalid. Tests are never weakened, deleted or skipped to get green.

A per-task gate checks the build, the task's tests, scope and the hand-off before
the task is marked done. An analysis task may legitimately conclude *no*; its
rigour is gated, never the direction of its answer.

## Deterministic test bar

Before any reviewer runs, the `test-bar-gate` skill executes only the solution's
profile-enabled, configured checks in **lint → type-check → unit tests → smoke**
order over the combined diff, failing fast. Disabled checks are reported as
skips; an enabled check without a command is a configuration error, not a skip.
A runnable application must actually start and answer.

- Failures go back to the author with the failed check and location, for at most
  three corrective retries.
- Missing or invalid configuration stops the run rather than being skipped.
- Gate evidence is tied to the exact content verified; later edits require
  re-verification.

## Optional deploy-verify

When `infrastructure.deploy_verify: dev` is set, the feature branch is deployed
through the project's own pipeline to the first non-production environment, to
catch quota, policy and permission problems a plan cannot. It never targets
production.

Next: [Review and completion](review.md).
