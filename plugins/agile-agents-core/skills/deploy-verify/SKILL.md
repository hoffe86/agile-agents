---
name: deploy-verify
description: >-
  Opt-in deployed verification — push the feature branch, let the project's own CI/CD pipeline deploy pipeline + IaC + application to the first non-production environment, and report whether it actually deployed. Proves the things `plan` / `what-if` structurally cannot: quota, policy denial, name collisions, RBAC at apply time, unregistered providers, non-idempotent IaC. Gated on `solution-profile.yaml: infrastructure.deploy_verify` (default `off`) and never touches production. Loaded by `dev-lead` at Stage 7 after the test bar passes.
metadata:
  applies_to: all
---

# Deploy-Verify

Preview succeeding and deployment succeeding are different claims. This skill
verifies the second through **the project's own pipeline**, not a direct deploy.

Using the real pipeline also verifies workload identity, environment gates,
configuration and stage ordering. Direct provider commands would bypass the
delivery path being tested. Resolve technical operations from applicable,
actually available solution capabilities; otherwise use existing pipeline
definitions and authoritative docs and report the fallback. Missing access or
commands are unverified, never proof of deployment.

## What plan / what-if cannot catch

The justification for spending the time and the cloud money:

| Failure mode | Caught by plan / what-if? |
|---|---|
| Quota or regional capacity exhausted | ❌ |
| Organization/provider policy refuses the resource | ❌ preview may omit enforcement |
| Name collision, or a retained soft-deleted resource | ❌ |
| Deploy identity lacks a role only needed at apply time | ❌ |
| Required service capability not enabled for the account | ❌ |
| IaC is not idempotent — a second apply still shows changes | ❌ |
| Module outputs resolve to something the next module can consume | ❌ |
| Application actually starts on the deployed infrastructure | ❌ |

**Run the cheap check first.** Use the solution's existing validation,
non-mutating preview and permission checks before spending a deployment.
A failed required preflight cannot reach this gate; an unresolved command is
a configuration gap, not permission to guess a provider recipe.

## When this skill fires

At **Stage 7**, immediately after the test bar returns green, and only when **all** preconditions hold. Any precondition unmet → emit a `skipped` event with the specific reason and pass through. Never block a run because deployed verification was unavailable — it is an enhancement to the gate, not a new mandatory gate.

Preconditions:

1. `infrastructure.deploy_verify` is `dev`. Default is `off` → skip, no warning. Most repos have no non-prod environment wired for this and that is a normal state.
2. `infrastructure.environment_chain` is non-empty. The target is `environment_chain[0]`. If that entry's name contains `prod`, **halt and ask the user** — a chain whose first entry is production is a misconfiguration, and guessing is not safe.
3. `cicd.platform` is set and the pipeline definitions in `cicd.pipeline_paths` exist.
4. The diff actually touches something deployable — IaC, application source, or a pipeline definition. A docs-only or test-only diff skips with `reason=nothing_deployable`.
5. The branch is a feature branch, not the default branch.

## Branching strategy determines reachability

Read `cicd.release_strategy` and actual pipeline triggers/environment conditions
**before** pushing. No branching strategy alone proves deployment reachability.

If the strategy or the triggers say this branch will not reach a dev deploy, emit `skipped, reason=branch_not_deployable` and say so plainly in the report. **Do not** "fix" it by pushing to `develop`, retargeting the pipeline, or adding a trigger — that is a change to the project's release process, far outside the mandate of a verification step.

## Procedure

1. **Confirm the target.** Resolve `environment_chain[0]`. Re-assert it is not production. This is the one check worth doing twice.
2. **Push the branch** only within the caller's write authority and consent
   constraints. Commit the intended work on the feature branch first; never
   force-push or push to the default branch. A no-push instruction blocks this
   step; report unverified. This skill opens no PR.
3. **Find the run.** Locate the pipeline run triggered by that head SHA. If no run appears within ~2 minutes, emit `skipped, reason=no_pipeline_run` — the triggers did not match, which is information, not a failure.
   Record that SHA with the evidence. After corrective edits to deployable
   content, repeat verification for the new SHA before re-review; do not reuse
   an old green run. Recheck all preconditions and retain the existing retry
   count, non-production boundary, and explicit skip reasons.
4. **Establish an operation timeout before polling.** Use an explicit end-to-end
   polling timeout already documented by the project/pipeline or supplied by
   the user, not a single job timeout that excludes queue time. Record its
   source, duration, and fixed deadline before the first poll. Include queued
   time; bound each status request and sleep by the time left. Do not reset
   the deadline on a status change or resume. If no bound is established,
   report `failure, reason=timeout_not_configured` and the run URL, and stop
   verification without polling; a bound is required before retrying.
   On expiry: `failure, reason=timeout`; stop polling and report the run URL
   so a human can pick it up. Do not cancel the pipeline.
5. **Read the outcome.** On failure, extract the failing stage/job name and the error tail. A pipeline URL alone is not a report.
6. **Assert convergence.** Run the solution's non-mutating preview against the
   deployed environment. **An empty diff is the pass condition.** A non-empty
   diff after a successful apply is a failure, even if the pipeline is green.
   Missing preview commands/access leave convergence unverified.
7. **Application liveness**, when the pipeline does not already assert it: one request to the deployed health endpoint. Same shape as the smoke slot in `test-bar-gate`, pointed at the deployed URL rather than localhost.
8. **Post-deploy telemetry.** When applicable solution telemetry and authorized
   query capabilities are available, inspect exception and failed-request
   counts since this deployment. A green deploy can still fail on first use.
   Missing telemetry/access is a stated unverified step, neither pass nor failure.

## Teardown

This contract targets a **long-lived non-production environment the solution
already owns**. Do not delete it or create per-run infrastructure. Preserve the
solution's environment lock/serialization: concurrent deployments to one target
make evidence ambiguous. Report conflicting runs rather than claiming verification.

## Cost

`cost_envelope` gates tokens, AIU, and rated USD, not cloud-resource spend.
`max_minutes_per_run` is informational planning only, not an enforced deadline
or a source of remaining polling time. Use the operation timeout above; never
poll indefinitely. Keep the normal cost checkpoints and retry limits.
Use the solution's infrastructure budget and alerts: a token budget cannot see
a resource left running. Do not provision budget resources from this skill.

## Failure attribution

Feeds the same corrective loop as the test bar — up to three retries, then halt and ask.

| Failing stage | Author to re-engage |
|---|---|
| IaC deployment | `infrastructure` |
| Non-empty diff on the convergence re-plan | `infrastructure` |
| Application build or deploy step | `coding` |
| Application health check after a successful deploy | `coding` |
| Exceptions / failed requests in post-deploy telemetry | `coding` — the deploy worked, the app does not |
| Pipeline definition itself (syntax, auth, missing variable) | `infrastructure` |
| Quota, policy denial, missing role assignment | **halt — ask the user.** These need an authorized platform owner, not another agent round. |

That last row matters: an agent cannot raise a quota or grant itself a role, and retrying will burn the envelope on a deterministic failure.

## Event log

Emit to the run event log (`run-event-log`):

```json
{ "event_type": "deploy_verify", "outcome": "success", "environment": "dev", "run_url": "https://…", "duration_s": 412, "convergence": "empty" }
{ "event_type": "deploy_verify", "outcome": "skipped", "reason": "not_configured" }
{ "event_type": "deploy_verify", "outcome": "failure", "environment": "dev", "run_url": "https://…", "failed_stage": "deploy-infra", "error_tail": "…" }
```

## Hard rules

- **Never production.** Not the last entry of `environment_chain`, not any entry whose name contains `prod`, regardless of configuration.
- **Never merge, never force-push, never rewrite shared history.** Pushing the feature branch is the entire write footprint.
- **Never modify pipeline triggers to make a deploy happen.** If the branch does not reach the environment, report that.
- **Skip loudly, fail loudly, never silently pass.** A skipped verification must appear in the hand-off — a run that reports "verified" when it only ran `plan` is worse than one that never tried.
